"""Teksty jednolite dostępne tylko w PDF — nieurzędowy odczyt z urzędowego PDF.

Od 2025 r. API ELI Sejmu nie publikuje HTML dla aktów Dziennika Ustaw, więc
najnowsze teksty jednolite kodeksów są wyłącznie w PDF. Ten moduł pobiera
urzędowy PDF, konwertuje go u siebie konwerterem eli2md (przypięta wersja,
pdfplumber) i wycina artykuł z drzewa jednostek redakcyjnych. Wynik jest
NIEURZĘDOWYM odczytem: wiążący pozostaje PDF, a odczyt przechodzi kontrole,
zanim narzędzie go odda — przy wątpliwości wolimy odmówić niż podać treść.

Kontrole wierności odczytu (czy konwersja oddaje dokument):
  1. struktura — nagłówki artykułów idą w kolejności rosnącej, artykuł jest
     węzłem drzewa, a nie tekstem cytowanym w przepisie przejściowym;
  2. warstwa tekstowa PDF — tekst artykułu musi być uporządkowanym podciągiem
     słów odczytanych z tego samego PDF drugim, niezależnym czytnikiem
     (poppler/pdftotext; eli2md czyta przez pdfminer), a słowa pominięte przez
     konwerter w obrębie artykułu mogą być tylko nagłówkami stron i przypisami;
  3. starszy tekst jednolity w HTML — źródło urzędowe i niezależne od PDF:
     artykuł identyczny potwierdza odczyt; różny musi mieć wytłumaczenie
     (odnośnik przy jednostce albo nowelizacja między datami obu tekstów).

Aktualność prawna to osobna ocena od wierności: poprawnie odczytany tekst
jednolity może już wymagać uwzględnienia nowelizacji ogłoszonych po nim.
"""
from __future__ import annotations

import asyncio
import dataclasses
import datetime as _dt
import hashlib
import logging
import os
import pathlib
import re
import shutil
import subprocess
import tempfile
import unicodedata

import httpx

logger = logging.getLogger(__name__)

BASE = "https://api.sejm.gov.pl/eli/acts"
_HEADERS = {"User-Agent": "legal-cite/0.1 (+https://github.com/apiotrowski-afk/legal-cite-pl)"}

# Katalog na pobrane PDF-y i wyniki konwersji. Konwersja kodeksu trwa od 30 s
# (k.c.) do ponad minuty (k.p.c.), więc wynik trzymamy na dysku, pod kluczem
# z sumy PDF i wersji konwertera — zmiana jednego lub drugiego unieważnia cache.
CACHE_DIR = pathlib.Path(os.environ.get("LEGAL_CITE_CACHE")
                         or pathlib.Path(tempfile.gettempdir()) / "legal-cite")

# Największa dopuszczalna przerwa (w słowach) między kolejnymi słowami artykułu
# w warstwie tekstowej PDF: nagłówek strony i przypisy u jej dołu rozdzielają
# treść artykułu, ale nie o więcej niż kilkaset słów (długie przypisy
# z adresami Dz.Urz. UE sięgają kilkuset).
_MAX_PRZERWA = 1500
# Słowa warstwy tekstowej pominięte przez konwerter w obrębie artykułu, których
# nie tłumaczą nagłówki stron, przypisy ani numery odnośników.
_MAX_NIEWYJASNIONE = 0

_STOPKA = {"dziennik", "ustaw", "poz", "s", "kancelaria", "sejmu"}


def wersja_konwertera() -> str:
    try:
        from importlib.metadata import version
        return f"eli2md {version('eli2md')} / pdfplumber {version('pdfplumber')}"
    except Exception:
        return "eli2md (wersja nieznana)"


def wersja_pdftotext() -> str | None:
    if not shutil.which("pdftotext"):
        return None
    try:
        out = subprocess.run(["pdftotext", "-v"], capture_output=True, text=True, timeout=10)
        m = re.search(r"pdftotext version (\S+)", out.stderr + out.stdout)
        return f"pdftotext {m.group(1)}" if m else "pdftotext"
    except Exception:
        return "pdftotext"


def konwerter_dostepny() -> bool:
    try:
        import eli2md.pdf  # noqa: F401
        import eli2md.tree  # noqa: F401
        return True
    except Exception:
        return False


# --- normalizacja tekstu do porównań --------------------------------------

def _indeks(ch: str) -> bool:
    """Czy znak jest cyfrą lub literą w indeksie górnym (²,ᵃ)."""
    if ch.isascii():
        return False
    n = unicodedata.normalize("NFKC", ch)
    return n != ch and n.isalnum()


OPC = "\x01"  # znacznik słowa opcjonalnego (indeks górny numeru jednostki)


def _rozdziel_indeksy(s: str) -> str:
    """„22¹ᵃ” → „22 \x011a”: indeks staje się osobnym słowem (w druku 2026 r.
    „22[1a]”), oznaczonym jako opcjonalne — pdftotext gubi indeks złożony
    prawdziwym pismem górnym („Art. 18 .” zamiast „Art. 18⁴.”), więc jego brak
    w warstwie tekstowej nie może przesądzać o odmowie."""
    out, poprzedni = [], False
    for ch in s:
        jest = _indeks(ch)
        if jest and not poprzedni:
            out.append(" " + OPC)
        out.append(unicodedata.normalize("NFKC", ch) if jest else ch)
        poprzedni = jest
    return "".join(out)


_PRZYPIS_RE = re.compile(r"\[\^([^\]\s]+)\]")
_NOTKA_RE = re.compile(r"[⁰¹²³⁴⁵⁶⁷⁸⁹]+⁾")
_SLOWO_RE = re.compile(r"\x01?[^\W_]+", re.UNICODE)
_LITERA_CYFRA_RE = re.compile(r"(?<=[^\W\d_])(?=\d)", re.UNICODE)


def tokeny(s: str, opcjonalne: bool = False) -> list[str]:
    """Słowa do porównań: bez odnośników, NFKC, małe litery, same znaki
    alfanumeryczne. Cyfra doklejona do litery („zdrowotnej44” — numer
    odnośnika bez odstępu) to osobne słowo. Z opcjonalne=True słowa z indeksu
    górnego zaczynają się znacznikiem OPC."""
    s = _PRZYPIS_RE.sub(" ", s)
    s = _NOTKA_RE.sub(" ", s)
    s = _rozdziel_indeksy(s)
    s = unicodedata.normalize("NFKC", s).lower()
    s = _LITERA_CYFRA_RE.sub(" ", s)
    # „\x01§ 1” → znacznik przechodzi na słowo „1”, znak § i tak wypada
    s = re.sub(r"\x01([\W_]+)", lambda m: m.group(1) + OPC, s)
    out = _SLOWO_RE.findall(s)
    return out if opcjonalne else [t.lstrip(OPC) for t in out]


def _tokeny_pdftotext(raw: str) -> list[str]:
    # łamanie wyrazu na końcu wiersza: „wynagro-\ndzenia” → „wynagrodzenia”
    raw = re.sub(r"(\w)-\n(?=[a-ząćęłńóśźż])", r"\1", raw)
    return tokeny(raw)


# --- drzewo jednostek z Markdown eli2md -----------------------------------

@dataclasses.dataclass
class Jednostka:
    num: str                 # numer w zapisie źródła: „18³ᵈ”, „36a”
    klucz: str               # zapis kanoniczny jak w data-id HTML: „18_3d”, „36a”
    tekst: str               # pełny tekst artykułu z etykietami jednostek (ze znacznikami OPC)
    odnosniki: list[str]     # numery przypisów przy tej jednostce
    data: _dt.date | None    # od kiedy obowiązuje to brzmienie (z odnośnika), gdy znana

    def czysty(self) -> str:
        """Tekst do pokazania: bez znaczników opcjonalności."""
        return self.tekst.replace(OPC, "")


def kanon_md(num: str) -> str | None:
    """„18³ᵈ” → „18_3d”, „5[1q]” → „5_1q”, „36a” → „36a”, „22” → „22”."""
    m = re.match(r"^(\d+)([a-ząćęłńóśźż]?)(.*)$", num.strip())
    if not m:
        return None
    reszta = m.group(3).replace("[", "").replace("]", "").strip(". ")
    idx = unicodedata.normalize("NFKC", reszta).lower()
    if idx and not re.fullmatch(r"\d+[a-ząćęłńóśźż]*", idx):
        return None
    return m.group(1) + m.group(2) + (f"_{idx}" if idx else "")


# Etykiety jednostek niższych niż artykuł są w tekście do porównań opcjonalne
# (znacznik OPC): pdftotext wypisuje numery punktów osobno od ich treści, więc
# w warstwie tekstowej stoją w innym miejscu niż w odczycie.
_ETYKIETY = {"art": "Art. {n}.", "par": OPC + "§ {n}.", "ust": OPC + "{n}.",
             "pkt": OPC + "{n})", "lit": OPC + "{n})", "tir": "–"}
# Nagłówek jednostki systematyzującej („DZIAŁ PIĄTY”, „CZĘŚĆ PIERWSZA POSTĘPOWANIE
# ROZPOZNAWCZE”, „Rozdział I”), który konwerter potrafi przypisać jako tekst do
# poprzedzającego go artykułu — zwłaszcza po „(uchylony)”. Od niego w dół nic
# już nie należy do artykułu.
_NAGLOWEK_RE = re.compile(
    r"^(?:(?:DZIAŁ|ROZDZIAŁ|ODDZIAŁ|TYTUŁ|KSIĘGA|CZĘŚĆ)\s+[A-ZĄĆĘŁŃÓŚŹŻIVXLC\d]+\b"
    r"|(?:Dział|Rozdział|Oddział|Tytuł|Księga|Część)\s+(?:[IVXLC]+|\d+[a-z]?)\b\.?\s*$)")


def _tekst_wezla(node: dict, odn: list[str], stop: list[bool]) -> str:
    typ = node.get("type")
    czesci = []
    if typ in _ETYKIETY:
        czesci.append(_ETYKIETY[typ].format(n=node.get("num", "")))
    if node.get("text"):
        czesci.append(node["text"])
    for ch in node.get("children") or []:
        if stop[0]:
            break
        if ch.get("type") in ("heading", "signature", "note"):
            stop[0] = True
            break
        if ch.get("type") == "text" and _NAGLOWEK_RE.match(_PRZYPIS_RE.sub("", ch.get("text") or "")):
            stop[0] = True
            break
        czesci.append(_tekst_wezla(ch, odn, stop))
    s = " ".join(c for c in czesci if c)
    odn.extend(_PRZYPIS_RE.findall(s))
    s = _PRZYPIS_RE.sub("", s)
    s = re.sub(r"(?m)^\\(?=[>#])", "", s)
    return re.sub(r"\s+", " ", s).strip()


def jednostki_md(md: str, przypisy: dict[str, str]) -> tuple[list[Jednostka], bool]:
    """Artykuły z drzewa eli2md w kolejności dokumentu oraz flaga, czy ich
    numery rosną monotonicznie (drugie brzmienie tego samego artykułu jest
    dozwolone — stoi obok pierwszego)."""
    from eli2md.tree import md_to_tree
    from legal_cite.core import _data_wejscia

    drzewo = md_to_tree(md)
    # Tekst jednolity jest załącznikiem do obwieszczenia Marszałka Sejmu, więc
    # artykuły ustawy stoją w załączniku, a nie w treści głównej. Bierzemy ten
    # blok dokumentu, w którym jest najwięcej artykułów.
    bloki = [drzewo.get("body") or []] + [a.get("body") or [] for a in drzewo.get("annexes") or []]
    wezly = max(bloki, key=lambda b: sum(1 for n in b if n.get("type") == "art"))
    out: list[Jednostka] = []
    monotonicznie, poprzedni = True, -1
    for node in wezly:
        if node.get("type") != "art":
            continue
        num = str(node.get("num", ""))
        klucz = kanon_md(num)
        if not klucz:
            continue
        baza = int(re.match(r"\d+", klucz).group(0))
        if baza < poprzedni:
            monotonicznie = False
        poprzedni = baza
        odn: list[str] = []
        tekst = _tekst_wezla(node, odn, [False])
        data = _data_wejscia(przypisy, odn[0]) if odn else None
        out.append(Jednostka(num, klucz, tekst, odn, data))
    return out, monotonicznie


def przypisy_md(md: str) -> dict[str, str]:
    mapa: dict[str, str] = {}
    for m in re.finditer(r"(?m)^\[\^([^\]\s]+)\]:\s*(.*(?:\n(?!\[\^|\n).*)*)", md):
        mapa.setdefault(m.group(1), re.sub(r"\s+", " ", m.group(2)).strip())
        # odesłania w przypisach używają numeru bez przyrostka strony
        mapa.setdefault(m.group(1).split("_")[0], mapa[m.group(1)])
    return mapa


# --- kontrola wierności: warstwa tekstowa PDF (pdftotext) -----------------

@dataclasses.dataclass
class WynikWiernosci:
    ok: bool
    powod: str = ""
    niewyjasnione: list[str] = dataclasses.field(default_factory=list)


def _dopasuj(md_tok: list[str], raw_tok: list[str], start: int,
             max_przerwa: int) -> tuple[int, int, list[int]] | None:
    """Dopasowuje słowa artykułu jako uporządkowany podciąg warstwy tekstowej
    od pozycji start. Zwraca (pierwsza, za_ostatnią, pozycje_dopasowane) albo
    None. Toleruje wyraz złamany na końcu wiersza (dwa słowa warstwy = jedno
    słowo artykułu) i odwrotnie (słowo warstwy = dwa słowa artykułu). Słowo
    opcjonalne (indeks górny) może w warstwie nie wystąpić."""
    i, j = start, 0
    pozycje: list[int] = []
    pierwsza = -1
    n_md, n_raw = len(md_tok), len(raw_tok)
    while j < n_md:
        t = md_tok[j]
        opcjonalne = t.startswith(OPC)
        t = t.lstrip(OPC)
        nast = md_tok[j + 1].lstrip(OPC) if j + 1 < n_md else None
        k, limit = i, min(n_raw, i + (3 if opcjonalne else max_przerwa) + 1)
        trafiony = None
        while k < limit:
            r = raw_tok[k]
            if r == t:
                trafiony = (k + 1, 1)
                break
            if k + 1 < n_raw and raw_tok[k] + raw_tok[k + 1] == t:
                trafiony = (k + 2, 1)
                pozycje.append(k)
                break
            if nast is not None and r == t + nast:
                trafiony = (k + 1, 2)
                break
            # numer odnośnika doklejony do liczby bez odstępu („pkt 10–20⁵” → „205”):
            # liczba + 1–2 cyfry, a tuż za nią następne słowo artykułu
            if (t.isdigit() and r.startswith(t) and r[len(t):].isdigit()
                    and len(r) - len(t) <= 2 and nast is not None
                    and k + 1 < n_raw and raw_tok[k + 1] == nast):
                trafiony = (k + 1, 1)
                break
            k += 1
        if trafiony is None:
            if opcjonalne:
                j += 1
                continue
            return None
        if pierwsza < 0:
            pierwsza = k
        pozycje.append(k)
        i, skok = trafiony
        j += skok
    if pierwsza < 0:
        return None
    return pierwsza, i, pozycje


def wiernosc_pdftotext(jedn: Jednostka, raw_tok: list[str], dozwolone: set[str],
                       max_przerwa: int = _MAX_PRZERWA) -> WynikWiernosci:
    md_tok = tokeny(jedn.tekst, opcjonalne=True)
    if len(md_tok) < 2:
        return WynikWiernosci(False, "pusty odczyt artykułu")
    # kandydaci na początek: wystąpienia „Art. N” w warstwie (także z numerem
    # zlepionym z indeksem: „15110”), od których pierwsze słowa artykułu
    # dopasowują się ciasno — odesłania „art. N” w zdaniach odpadają, bo po
    # nich nie następuje treść tego artykułu
    t0, t1 = md_tok[0].lstrip(OPC), md_tok[1].lstrip(OPC)
    t2 = md_tok[2].lstrip(OPC) if len(md_tok) > 2 else ""
    kandydaci = [k for k in range(len(raw_tok) - 1)
                 if raw_tok[k] == t0 and raw_tok[k + 1] in (t1, t1 + t2)]
    if not kandydaci:
        return WynikWiernosci(False, "nagłówka artykułu nie ma w warstwie tekstowej PDF")
    # głowa: ~10 pierwszych słów, wydłużona o słowo opcjonalne, które by ucięła
    # (indeks górny sklejony w warstwie z numerem: „art. 35¹⁹” → „3519”)
    n_glowy = min(10, len(md_tok))
    while n_glowy < len(md_tok) and md_tok[n_glowy].startswith(OPC):
        n_glowy += 1
    glowa = md_tok[:n_glowy]
    najlepszy: WynikWiernosci | None = None
    for k in kandydaci:
        if _dopasuj(glowa, raw_tok, k, max_przerwa=3) is None:
            continue
        wynik = _dopasuj(md_tok, raw_tok, k, max_przerwa)
        if wynik is None:
            najlepszy = najlepszy or WynikWiernosci(
                False, "słowa odczytu nie układają się w kolejności warstwy tekstowej PDF")
            continue
        pierwsza, za, pozycje = wynik
        uzyte = set(pozycje)
        # etykiety punktów i liter („9a”, „g”) pdftotext wypisuje w innym miejscu
        # niż treść, więc pominięte przy dopasowaniu nie świadczą o utracie tekstu
        etykiety = {t.lstrip(OPC) for t in md_tok if t.startswith(OPC)}
        niewyjasnione = [raw_tok[p] for p in range(pierwsza, za)
                         if p not in uzyte and raw_tok[p] not in dozwolone
                         and raw_tok[p] not in etykiety and not raw_tok[p].isdigit()]
        if len(niewyjasnione) <= _MAX_NIEWYJASNIONE:
            return WynikWiernosci(True)
        # drugie brzmienie tego samego artykułu stoi tuż za pierwszym: dopasowanie
        # od pierwszego „przeskakuje” jego treść — próbujemy od kolejnego kandydata
        if najlepszy is None or len(niewyjasnione) < len(najlepszy.niewyjasnione):
            najlepszy = WynikWiernosci(
                False, "warstwa tekstowa PDF zawiera w obrębie artykułu słowa, których nie ma "
                f"w odczycie: {niewyjasnione[:6]}", niewyjasnione)
    return najlepszy or WynikWiernosci(
        False, "słowa odczytu nie układają się w kolejności warstwy tekstowej PDF")


# --- pobranie, konwersja, cache -------------------------------------------

@dataclasses.dataclass
class OdczytPDF:
    ident: str                       # DU/2026/1245
    url_pdf: str
    sha256: str
    data_tj: str                     # announcementDate tekstu jednolitego
    adres: str                       # „Dz.U. 2026 poz. 1245”
    konwerter: str
    pdftotext: str | None
    jednostki: list[Jednostka]
    przypisy: dict[str, str]
    monotoniczne: bool
    raw_tok: list[str]
    dozwolone: set[str]              # słowa przypisów i stopek, które warstwa ma, a odczyt nie

    def znajdz(self, klucz: str) -> list[Jednostka]:
        return [j for j in self.jednostki if j.klucz == klucz]


_odczyty: dict[str, OdczytPDF] = {}
_blokady: dict[str, asyncio.Lock] = {}


def _konwertuj(pdf_path: pathlib.Path, md_path: pathlib.Path) -> str:
    if md_path.exists():
        return md_path.read_text(encoding="utf-8")
    from eli2md.pdf import convert, to_markdown
    md = to_markdown(convert(str(pdf_path)))
    md_path.write_text(md, encoding="utf-8")
    return md


def _warstwa(pdf_path: pathlib.Path, txt_path: pathlib.Path) -> str | None:
    if txt_path.exists():
        return txt_path.read_text(encoding="utf-8")
    if not shutil.which("pdftotext"):
        return None
    subprocess.run(["pdftotext", "-enc", "UTF-8", str(pdf_path), str(txt_path)],
                   check=True, timeout=120, capture_output=True)
    return txt_path.read_text(encoding="utf-8")


async def odczyt(ident: str, meta_tj: dict | None = None) -> OdczytPDF:
    """Pobiera PDF tekstu jednolitego ident (np. DU/2026/1245), konwertuje go
    (w wątku, bo trwa to do ponad minuty) i przygotowuje dane do kontroli.
    Wynik trzymany w pamięci procesu i na dysku."""
    if ident in _odczyty:
        return _odczyty[ident]
    lock = _blokady.setdefault(ident, asyncio.Lock())
    async with lock:
        if ident in _odczyty:
            return _odczyty[ident]
        pub, year, pos = ident.split("/")
        url_pdf = f"{BASE}/{pub}/{year}/{pos}/text.pdf"
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        pdf_path = CACHE_DIR / f"{pub}_{year}_{pos}.pdf"
        async with httpx.AsyncClient(follow_redirects=True, timeout=60, headers=_HEADERS) as c:
            if meta_tj is None:
                meta_tj = (await c.get(f"{BASE}/{ident}")).json()
            if not pdf_path.exists() or pdf_path.stat().st_size == 0:
                resp = await c.get(url_pdf)
                resp.raise_for_status()
                if not resp.content.startswith(b"%PDF"):
                    raise RuntimeError(f"{ident}: odpowiedź API nie jest plikiem PDF")
                pdf_path.write_bytes(resp.content)
        sha = hashlib.sha256(pdf_path.read_bytes()).hexdigest()
        wersja = wersja_konwertera()
        stempel = hashlib.sha256((sha + wersja).encode()).hexdigest()[:16]
        md_path = CACHE_DIR / f"{pub}_{year}_{pos}_{stempel}.md"
        txt_path = CACHE_DIR / f"{pub}_{year}_{pos}_{sha[:16]}.txt"
        md, raw = await asyncio.gather(
            asyncio.to_thread(_konwertuj, pdf_path, md_path),
            asyncio.to_thread(_warstwa, pdf_path, txt_path))
        przypisy = przypisy_md(md)
        jednostki, monotoniczne = jednostki_md(md, przypisy)
        raw_tok = _tokeny_pdftotext(raw) if raw else []
        dozwolone = set(_STOPKA) | {pos}
        for tresc in przypisy.values():
            dozwolone.update(tokeny(tresc))
        wynik = OdczytPDF(ident=ident, url_pdf=url_pdf, sha256=sha,
                          data_tj=meta_tj.get("announcementDate") or "",
                          adres=meta_tj.get("displayAddress") or ident,
                          konwerter=wersja, pdftotext=wersja_pdftotext() if raw else None,
                          jednostki=jednostki, przypisy=przypisy, monotoniczne=monotoniczne,
                          raw_tok=raw_tok, dozwolone=dozwolone)
        logger.info("odczyt pdf %s: artykulow=%d monotonicznie=%s pdftotext=%s",
                    ident, len(jednostki), monotoniczne, bool(raw))
        _odczyty[ident] = wynik
        return wynik


# --- kontrola względem starszego tekstu jednolitego w HTML ------------------

def porownaj_z_html(jedn: Jednostka, html_teksty: list[str]) -> str:
    """'identyczny' — te same słowa co w starszym t.j. HTML (także gdy warstwa
    PDF skleja wyrazy: „niewięcej”); 'rozny' — inna treść; 'brak' — artykułu
    nie ma w starszym tekście (dodany później)."""
    if not html_teksty:
        return "brak"
    moje = "".join(tokeny(jedn.tekst))
    for h in html_teksty:
        if "".join(tokeny(h)) == moje:
            return "identyczny"
    return "rozny"


def slownik_html(html_teksty) -> set[str]:
    """Słowa starszego tekstu jednolitego w HTML — słownik do naprawy sklejek."""
    out: set[str] = set()
    for t in html_teksty:
        out.update(tokeny(t))
    return out


_NIE_RE = re.compile(r"\b([Nn]ie)([a-ząćęłńóśźż]{3,})\b")


def napraw_sklejki(tekst: str, slownik: set[str]) -> tuple[str, int]:
    """Warstwa tekstowa PDF-ów Dz.U. nie ma odstępu po „nie” przed niektórymi
    wyrazami („niewięcej”, „niepóźniej”) — tak czytają ją oba czytniki, więc
    nie jest to błąd konwertera, tylko druku. Rozdzielamy wyłącznie wtedy, gdy
    sklejki nie ma w słowniku słów tego aktu (HTML), a jej reszta w nim jest."""
    if not slownik:
        return tekst, 0
    ile = 0

    def _f(m):
        nonlocal ile
        calosc, reszta = m.group(0), m.group(2)
        if calosc.lower() not in slownik and reszta.lower() in slownik:
            ile += 1
            return f"{m.group(1)} {reszta}"
        return calosc
    return _NIE_RE.sub(_f, tekst), ile
