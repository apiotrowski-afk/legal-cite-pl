"""legal-cite — logika weryfikacji brzmienia przepisu z OFICJALNEGO źródła.

Pobiera dokładny tekst cytowanego artykułu (api.sejm.gov.pl dla prawa PL,
EUR-Lex dla prawa UE) i zwraca TYLKO ten artykuł — nie cały akt. Akty są
cache'owane w obrębie sesji procesu. AKTUALNE brzmienie (tekst jednolity),
nie pierwotne z dnia ogłoszenia.
"""
from __future__ import annotations

import bisect
import datetime as _dt
import html as _html
import re

import logging
import httpx

# --- Akty PL → ELI: api.sejm.gov.pl/eli/acts/{pub}/{year}/{pos}/text.html ---
# pos = pozycja w Dzienniku Ustaw (poz. N)
PL_ACTS: dict[str, dict] = {
    "KC":       dict(pub="DU", year=1964, pos=93,   name="Kodeks cywilny"),
    "KP":       dict(pub="DU", year=1974, pos=141,  name="Kodeks pracy"),
    "KSH":      dict(pub="DU", year=2000, pos=1037, name="Kodeks spółek handlowych"),
    "KPC":      dict(pub="DU", year=1964, pos=296,  name="Kodeks postępowania cywilnego"),
    "KK":       dict(pub="DU", year=1997, pos=553,  name="Kodeks karny"),
    "PrAut":    dict(pub="DU", year=1994, pos=83,   name="Prawo autorskie i prawa pokrewne"),
    "u.r.p.":   dict(pub="DU", year=1982, pos=145,  name="Ustawa o radcach prawnych"),
    "u.ś.u.d.e.": dict(pub="DU", year=2002, pos=1204, name="Ustawa o świadczeniu usług drogą elektroniczną"),
    "u.z.n.k.": dict(pub="DU", year=1993, pos=211,  name="Ustawa o zwalczaniu nieuczciwej konkurencji"),
    "u.p.k.":   dict(pub="DU", year=2014, pos=827,  name="Ustawa o prawach konsumenta"),
    "UODO":     dict(pub="DU", year=2018, pos=1000, name="Ustawa o ochronie danych osobowych"),
    # sprawy kredytu konsumenckiego / SKD: art. 45 sankcja kredytu darmowego, art. 30 obowiązki
    "u.k.k.":   dict(pub="DU", year=2011, pos=715,  name="Ustawa o kredycie konsumenckim"),
    "UKK":      dict(pub="DU", year=2011, pos=715,  name="Ustawa o kredycie konsumenckim"),
}

# --- Akty UE → EUR-Lex (tekst polski), klucz = CELEX ---
EU_ACTS: dict[str, dict] = {
    "RODO":   dict(celex="32016R0679", name="Rozporządzenie 2016/679 (RODO/GDPR)"),
    "DSA":    dict(celex="32022R2065", name="Rozporządzenie 2022/2065 (DSA)"),
    "AI Act": dict(celex="32024R1689", name="Rozporządzenie 2024/1689 (AI Act)"),
    "AIA":    dict(celex="32024R1689", name="Rozporządzenie 2024/1689 (AI Act)"),
    "NIS2":   dict(celex="32022L2555", name="Dyrektywa 2022/2555 (NIS2)"),
    "DGA":    dict(celex="32022R0868", name="Rozporządzenie 2022/868 (DGA)"),
    "DMA":    dict(celex="32022R1925", name="Rozporządzenie 2022/1925 (DMA)"),
    # sprawy kredytu konsumenckiego / SKD: dyrektywa o kredycie konsumenckim
    "CCD":          dict(celex="32008L0048", name="Dyrektywa 2008/48/WE (kredyt konsumencki)"),
    "2008/48":      dict(celex="32008L0048", name="Dyrektywa 2008/48/WE (kredyt konsumencki)"),
    "dyrektywa 2008/48": dict(celex="32008L0048", name="Dyrektywa 2008/48/WE (kredyt konsumencki)"),
}

_HEADERS = {"User-Agent": "legal-cite/0.1 (+https://github.com/apiotrowski-afk/legal-cite-pl)"}

# cache per-proces: klucz aktu → tekst (strip HTML) całego aktu
logger = logging.getLogger(__name__)

_zrodlo: dict[str, tuple] = {}
_cache: dict[str, str] = {}
# surowy HTML aktu — znaczniki jednostek redakcyjnych są pewniejsze niż regex
# po tekście, więc wycinanie artykułu idzie najpierw po nich
_html_cache: dict[str, str] = {}
_jedn_cache: dict[str, list] = {}
_odn_cache: dict[str, dict] = {}
# (klucz aktu, numer po naprawie) → numer, jaki wydrukowało źródło
_zlepki: dict[tuple[str, str], str] = {}


def _klucz_pl(info: dict) -> str:
    return f"PL:{info['pub']}:{info['year']}:{info['pos']}"


def _resolve(act: str, table: dict) -> str | None:
    """Dopasowuje kod aktu odpornie na końcowe kropki i wielkość liter
    (u.k.k./u.k.k/UKK → ten sam akt)."""
    if act in table:
        return act
    norm = act.lower().rstrip('.')
    idx = {k.lower().rstrip('.'): k for k in table}
    return idx.get(norm)


_SUP = str.maketrans("¹²³⁴⁵⁶⁷⁸⁹⁰", "1234567890")


def parse_citation(raw: str) -> dict | None:
    """Parsuje cytat: 'art. N[a][¹] [ust./§ M] [pkt/lit. X] KOD' → {art, ustep, act}.
    Obsługuje sufiks literowy (36a), indeks górny (385¹/385[1]/385(1)) i § jako
    jednostkę redakcyjną (KC numeruje paragrafami)."""
    m = re.match(
        r'(?:art\.|§)\s*'
        r'(\d+[a-z]?(?:\s*(?:[¹²³⁴⁵⁶⁷⁸⁹]+|\[\d+\]|\(\d+\)|\^\d+))?)\s*'  # numer art. + opc. indeks
        r'(?:(?:ust\.|§)\s*(\d+\w?))?\s*'                                 # ustęp ALBO paragraf
        r'(?:(?:pkt|lit\.)\s*\S+\s*)?(.+)',                               # pkt/lit ignorowane; kod aktu
        raw.strip(), re.IGNORECASE,
    )
    if not m:
        return None
    return {
        "art": m.group(1).strip(),
        "ustep": m.group(2),
        "act": m.group(3).strip().rstrip('.').strip(),
    }


def _art_regex(raw_art: str) -> str:
    """Buduje fragment regex dopasowujący numer artykułu w tekście źródła,
    tolerancyjnie na spacje. 385¹→'385\\s+1' (źródło: „Art. 385 1 ."),
    36a→'36\\s*a', 45→'45'."""
    s = re.sub(r'([¹²³⁴⁵⁶⁷⁸⁹⁰]+)', lambda mm: ' ' + mm.group(1).translate(_SUP), raw_art.strip())
    s = re.sub(r'\s*[\[\(\^]\s*(\d+)\s*[\]\)]?', r' \1', s)  # [1]/(1)/^1 → " 1"
    s = re.sub(r'\s+', ' ', s).strip()
    parts = s.split(' ')
    if len(parts) == 2 and parts[1].isdigit():               # baza + indeks górny
        return rf'{re.escape(parts[0])}\s+{re.escape(parts[1])}'
    mlet = re.match(r'^(\d+)([a-zA-Z])$', parts[0])
    if mlet:                                                  # sufiks literowy 36a
        return rf'{mlet.group(1)}\s*{mlet.group(2)}'
    return re.escape(parts[0])


def _strip_html(raw_html: str) -> str:
    # 1) usuń <script>/<style> WRAZ z treścią — api.sejm.gov.pl wstrzykuje strukturę
    #    aktu jako JSON w <script>, inaczej kradłby dopasowanie nagłówka „Art. N.".
    raw_html = re.sub(r'<(script|style)\b[^>]*>.*?</\1>', ' ', raw_html,
                      flags=re.IGNORECASE | re.DOTALL)
    # 1a) usuń odnośniki redakcyjne (<a class="gloss-link">² wraz z treścią
    #     przypisu w tooltipie</a>). Źródło wstawia je WEWNĄTRZ nagłówka, więc
    #     „Art. 26." czytało się jako „Art. 26 9) W brzmieniu ustalonym przez…"
    #     — numer tracił kropkę, nagłówek przestawał istnieć i artykuł był
    #     nieznajdowalny. Przypis to komentarz wydawcy, nie treść przepisu.
    raw_html = re.sub(r'<a\b[^>]*class="[^"]*gloss-link[^"]*"[^>]*>.*?</a>', '', raw_html,
                      flags=re.IGNORECASE | re.DOTALL)
    # 2) strip tagów → 3) DEKODUJ encje (kluczowe: nagłówki to „Art.&nbsp;45." —
    #    &nbsp; to twarda spacja \xa0; po unescape regex „Art.\s*N." łapie) →
    # 4) zwiń białe znaki (w tym \xa0) do zwykłej spacji.
    text = re.sub(r'<[^>]+>', ' ', raw_html)
    text = _html.unescape(text)
    return re.sub(r'\s+', ' ', text).strip()


async def _fetch_pl(info: dict) -> str | None:
    """Pobiera AKTUALNY tekst aktu (tekst jednolity), nie pierwotny z dnia
    ogłoszenia. api.sejm `/text.html` pod pozycją oryginału zwraca brzmienie
    pierwotne (np. KC 1964 — „PRL", bez art. 385¹). Dlatego z metadanych bierzemy
    najnowszy tekst jednolity z dostępnym HTML; oryginał = fallback."""
    key = _klucz_pl(info)
    if key in _cache:
        return _cache[key]
    base = "https://api.sejm.gov.pl/eli/acts"
    async with httpx.AsyncClient(follow_redirects=True, timeout=25, headers=_HEADERS) as c:
        positions: list[tuple] = []
        zmieniajace: list[dict] = []
        try:
            meta = (await c.get(f"{base}/{info['pub']}/{info['year']}/{info['pos']}")).json()
            for ent in (meta.get("references") or {}).get("Inf. o tekście jednolitym", []):
                parts = (ent.get("id") or "").split("/")
                if len(parts) == 3:
                    positions.append(tuple(parts))  # (pub, year, pos) tekstu jednolitego
            zmieniajace = (meta.get("references") or {}).get("Akty zmieniające", [])
        except Exception:
            pass
        positions = positions[:4]  # najnowsze TJ (świeże bywają bez HTML — pomijamy puste)
        positions.append((info["pub"], str(info["year"]), str(info["pos"])))  # fallback oryginał
        for pub, year, pos in positions:
            try:
                resp = await c.get(f"{base}/{pub}/{year}/{pos}/text.html")
            except Exception:
                continue
            if resp.status_code == 200 and len(resp.text) > 3000:
                text = _strip_html(resp.text)
                if len(text) > 1500:
                    _cache[key] = text
                    _html_cache[key] = resp.text
                    # data tego TJ i liczba nowelizacji po niej — liczone tutaj,
                    # bo metadane są już pobrane; osobne zapytania przy każdym
                    # cytacie byłyby wolne i zawodne
                    data = ""
                    try:
                        data = ((await c.get(f"{base}/{pub}/{year}/{pos}"))
                                .json().get("announcementDate") or "")
                    except Exception:
                        pass
                    po = sum(1 for e in zmieniajace
                             if data and (e.get("date") or "") > data)
                    _zrodlo[key] = (f"{pub}/{year}/{pos}", data, po)
                    return text
    return None


async def _fetch_eu(info: dict) -> str | None:
    """Pobiera polski tekst aktu UE — najpierw z CELLAR, potem z EUR-Lex.

    Publiczna strona EUR-Lex stoi za WAF-em, który odpowiada 202 zamiast
    treści. Blokada nie jest stała: na tym samym kliencie potrafi włączyć się
    w ciągu dnia, więc nie da się jej obejść retrajem ani nagłówkiem. CELLAR
    to interfejs maszynowy Urzędu Publikacji z negocjacją treści — ten sam
    dokument, bez bramki dla przeglądarek.
    """
    key = f"EU:{info['celex']}"
    if key in _cache:
        return _cache[key]

    zrodla = (
        ("CELLAR",
         f"http://publications.europa.eu/resource/celex/{info['celex']}",
         {**_HEADERS, "Accept": "application/xhtml+xml", "Accept-Language": "pl"}),
        ("EUR-Lex",
         f"https://eur-lex.europa.eu/legal-content/PL/TXT/HTML/?uri=CELEX:{info['celex']}",
         _HEADERS),
    )
    for nazwa, url, headers in zrodla:
        try:
            async with httpx.AsyncClient(follow_redirects=True, timeout=30,
                                         headers=headers) as c:
                resp = await c.get(url)
        except httpx.HTTPError:
            continue
        # 202 = bramka WAF EUR-Lexu zwracająca stronę-wyzwanie zamiast aktu
        if resp.status_code != 200 or len(resp.text) < 10_000:
            logger.info("zrodlo=%s celex=%s http=%s dlugosc=%s — probuje dalej",
                        nazwa, info["celex"], resp.status_code, len(resp.text))
            continue
        _cache[key] = _strip_html(resp.text)
        _zrodlo[key] = (nazwa,)
        return _cache[key]
    return None


def _cut_ustep(art_text: str, ustep: str) -> str | None:
    # ustęp „N." LUB paragraf „§ N." (KC); granica = następna jednostka tej samej rangi
    m = re.search(rf'(?:§\s*)?(?<!\d){re.escape(ustep)}\.\s', art_text)
    if not m:
        return None
    ust_start = m.start()
    nxt = re.search(r'(?:§\s*)?(?<!\d)\d+\.\s', art_text[m.end():])
    ust_end = m.end() + nxt.start() if nxt else len(art_text)
    return art_text[ust_start:ust_end].strip()


# Minimalna wiarygodna długość treści. Próg niski, bo istnieją przepisy
# jednozdaniowe („Tworzy się Radę."); śmieci odsiewa dopiero udział liter.
_MIN_TRESC = 12


def _wiarygodny(art_text: str) -> bool:
    """Czy wycinek wygląda na treść przepisu, a nie na odesłanie lub śmieć.

    Narzędzie ma przeciwdziałać halucynacjom, więc cicha nieprawidłowość jest
    gorsza niż jawna odmowa — przy wątpliwości wolimy nie zwrócić nic.
    """
    # po odcięciu samego nagłówka „Art. N." musi zostać realna treść
    body = re.sub(r'^(?:Art\.|§)\s*[\d\sa-zA-Z]+\.', '', art_text, count=1).strip()
    # Przepis uchylony albo skreślony to prawidłowa odpowiedź, nie śmieć —
    # użytkownik ma się dowiedzieć, że artykuł nie obowiązuje.
    if re.match(r'^\(\s*(?:uchylon|skreślon|skreslon|pominięt|pominiet)\w*\s*\)', body, re.IGNORECASE):
        return True
    if len(body) < _MIN_TRESC:
        return False
    # Próg 30%, nie 50%: przepisy końcowe i odsyłające są gęste od numerów
    # artykułów i adresów publikacyjnych (47-48% liter), a odesłanie-śmieć
    # w rodzaju 'art. 1. ” „' ma liter zero.
    litery = sum(c.isalpha() for c in body)
    return litery >= len(body) * 0.3


_trzon_cache: dict[int, tuple[int, int]] = {}


def _trzon_aktu(text: str) -> tuple[int, int]:
    """Zakres pozycji, w którym leży właściwy akt (bez przepisów przejściowych).

    Tekst jednolity zawiera obok samego aktu także przepisy przejściowe ustaw
    nowelizujących, numerowane od nowa od „Art. 1.". Trzon aktu rozpoznajemy po
    tym, że jego artykuły tworzą najdłuższy rosnący ciąg nagłówków w kolejności
    dokumentu — bloki przejściowe są krótkie i zaczynają numerację od początku.
    """
    klucz = id(text)
    if klucz in _trzon_cache:
        return _trzon_cache[klucz]
    hd = [(m.start(), int(m.group(1)))
          for m in re.finditer(r'Art\.\s*(\d+)\s*\.', text)]
    if not hd:
        return (0, len(text))
    # Najdłuższy rosnący PODCIĄG, nie spójny ciąg: jeden nagłówek poza kolejnością
    # nie może dzielić trzonu na pół. W KPC źródło zlepia numer artykułu z
    # odnośnikiem („Art. 15.22)" → „Art. 1522.", data-id="arti_1522"), co przy
    # wymogu spójności odcinało art. 2-14 od reszty kodeksu i kazało ich odmawiać.
    konce: list[int] = []          # konce[k] = najmniejszy koniec podciągu długości k+1
    gdzie: list[int] = []          # indeks w hd tego końca
    poprz = [-1] * len(hd)
    for i, (_, n) in enumerate(hd):
        k = bisect.bisect_left(konce, n)
        poprz[i] = gdzie[k - 1] if k else -1
        if k == len(konce):
            konce.append(n)
            gdzie.append(i)
        else:
            konce[k] = n
            gdzie[k] = i
    naj = []
    i = gdzie[-1]
    while i >= 0:
        naj.append(hd[i])
        i = poprz[i]
    naj.reverse()
    zakres = (naj[0][0], naj[-1][0] + 4000)
    _trzon_cache[klucz] = zakres
    return zakres


def _trzon_wiarygodny(text: str) -> bool:
    """Czy wykryty trzon jest na tyle długi, by ufać mu przy odrzucaniu.

    Przy krótkich aktach albo nietypowej numeracji wykrycie może być mylne —
    wtedy lepiej zwrócić kandydata spoza zakresu niż odmówić wszystkiego.
    """
    lo, hi = _trzon_aktu(text)
    return sum(1 for m in re.finditer(r'Art\.\s*\d+\s*\.', text)
               if lo <= m.start() <= hi) >= 5


def _wybierz_po_sasiadach(text: str, art: str, kand: list) -> list:
    """Zostawia kandydata najlepiej wpasowanego między art. N-1 a art. N+1.

    Tekst jednolity zawiera na końcu przepisy przejściowe ustaw nowelizujących
    z własną numeracją od „Art. 1.", więc ten sam numer bywa w pliku dwa razy.
    Artykuły właściwego aktu idą po kolei i stoją blisko siebie, dlatego
    wybieramy wycinek o najmniejszej sumie odległości do sąsiadów. Sam warunek
    „leży pomiędzy" nie wystarcza, bo sąsiad również bywa zdublowany.
    """
    m = re.match(r'^(\d+)$', art.strip())
    if not m:
        return kand
    n = int(m.group(1))

    def poz(numer: int) -> list[int]:
        if numer < 1:
            return []
        return [x.start() for x in re.finditer(rf'Art\.\s*{numer}\s*\.', text)]

    przed, po = poz(n - 1), poz(n + 1)
    if not przed and not po:
        return kand

    def odleglosc(k) -> int:
        start = k[1]
        d = 0
        wczesniejsze = [p for p in przed if p < start]
        pozniejsze = [q for q in po if q > start]
        d += start - max(wczesniejsze) if wczesniejsze else 10 ** 7
        d += min(pozniejsze) - start if pozniejsze else 10 ** 7
        return d

    return [min(kand, key=odleglosc)]


_UNIT_RE = re.compile(r'<div class="unit unit_arti[^"]*" id="([^"]*)" data-id="arti_([^"]+)"')
_DIV_RE = re.compile(r'</?div\b[^>]*>', re.IGNORECASE)


def _koniec_div(raw_html: str, start: int) -> int:
    """Pozycja za znacznikiem zamykającym <div> otwarty na pozycji start."""
    glebokosc = 0
    for m in _DIV_RE.finditer(raw_html, start):
        if m.group(0)[1] == '/':
            glebokosc -= 1
            if glebokosc == 0:
                return m.end()
        else:
            glebokosc += 1
    return len(raw_html)


_ODNOSNIK_RE = re.compile(
    r'<a\b[^>]*class="[^"]*gloss-link[^"]*"[^>]*>\s*<sup>\s*(\d+)\s*\)\s*</sup>'
    r'\s*<span class="tooltip-text">(.*?)</span>\s*</a>', re.IGNORECASE | re.DOTALL)
_PIERWSZY_ODNOSNIK_RE = re.compile(
    r'<a\b[^>]*class="[^"]*gloss-link[^"]*"[^>]*>\s*<sup>\s*(\d+)\s*\)\s*</sup>',
    re.IGNORECASE)
_DO_WEJSCIA_RE = re.compile(r'obowiązuje\s+do\s+wejścia\s+w\s+życie', re.IGNORECASE)
_W_ZYCIE_RE = re.compile(
    r'w\s+życie\s+(?:z\s+dniem\s+)?(\d{1,2})\s+([a-ząćęłńóśźż]+)\s+(\d{4})',
    re.IGNORECASE)
_ODESLANIE_RE = re.compile(r'odnośnik\w*\s+(\d+)', re.IGNORECASE)
_MIESIACE = {'stycznia': 1, 'lutego': 2, 'marca': 3, 'kwietnia': 4, 'maja': 5,
             'czerwca': 6, 'lipca': 7, 'sierpnia': 8, 'września': 9,
             'października': 10, 'listopada': 11, 'grudnia': 12}


def _odnosniki(key: str, raw_html: str) -> dict[str, str]:
    """Numer odnośnika → jego treść. Źródło osadza treść przypisu w tooltipie
    przy każdym wywołaniu, więc wystarczy jedno przejście po dokumencie."""
    if key in _odn_cache:
        return _odn_cache[key]
    mapa: dict[str, str] = {}
    for nr, tresc in _ODNOSNIK_RE.findall(raw_html):
        mapa.setdefault(nr, _strip_html(tresc))
    _odn_cache[key] = mapa
    return mapa


def _data_wejscia(mapa: dict[str, str], nr: str, krok: int = 0) -> _dt.date | None:
    """Data, od której obowiązuje brzmienie opisane odnośnikiem nr.

    Odnośnik bywa odesłaniem („Przez art. 26 pkt 3 ustawy, o której mowa w
    odnośniku 3."), a data stoi dopiero w tym docelowym — dlatego idziemy po
    łańcuchu. Odnośnik mówiący „obowiązuje DO wejścia w życie zmiany" opisuje
    koniec, nie początek, więc nie daje daty.
    """
    tresc = mapa.get(nr)
    if tresc is None or krok > 3:
        return None
    if _DO_WEJSCIA_RE.search(tresc):
        return None
    m = _W_ZYCIE_RE.search(tresc)
    if m:
        mies = _MIESIACE.get(m.group(2).lower())
        if mies:
            try:
                return _dt.date(int(m.group(3)), mies, int(m.group(1)))
            except ValueError:
                return None
    dalej = _ODESLANIE_RE.search(tresc)
    return _data_wejscia(mapa, dalej.group(1), krok + 1) if dalej else None


def _kanon_art(raw_art: str) -> str | None:
    """Numer artykułu w zapisie, jakim posługuje się źródło w data-id:
    385¹/385[1]/385(1) → '385_1', 36a → '36a', 45 → '45'."""
    s = re.sub(r'\s+', '', raw_art.strip())
    s = re.sub(r'([¹²³⁴⁵⁶⁷⁸⁹⁰]+)', lambda m: '_' + m.group(1).translate(_SUP), s)
    s = re.sub(r'[\[\(\^]\s*(\d+)\s*[\]\)]?', r'_\1', s).lower()
    return s if re.fullmatch(r'\d+[a-ząćęłńóśźż]*(?:_\d+[a-ząćęłńóśźż]?)*', s) else None


def _jednostki_html(key: str, raw_html: str) -> list[tuple[str, str, _dt.date | None]]:
    """Artykuły właściwego aktu wg znaczników źródła, w kolejności dokumentu.

    Pomija przepisy przejściowe ustaw nowelizujących — źródło oznacza je
    prefiksem `pass_` w atrybucie id, więc nie trzeba ich zgadywać z numeracji.
    """
    if key in _jedn_cache:
        return _jedn_cache[key]
    mapa = _odnosniki(key, raw_html)
    out = []
    for m in _UNIT_RE.finditer(raw_html):
        if 'pass_' in m.group(1):
            continue
        fragment = raw_html[m.start():_koniec_div(raw_html, m.start())]
        odn = _PIERWSZY_ODNOSNIK_RE.search(fragment)
        out.append((m.group(2).lower(), _strip_html(fragment),
                    _data_wejscia(mapa, odn.group(1)) if odn else None))
    out = _napraw_zlepki(key, out)
    _jedn_cache[key] = out
    return out


def _napraw_zlepki(key: str, jedn: list[tuple]) -> list[tuple]:
    """Naprawia numer artykułu zlepiony z numerem odnośnika.

    Źródło drukuje art. 15 k.p.c. jako „Art. 15.22)" i oddaje w znaczniku
    `arti_1522`, więc artykuł był nieosiągalny pod swoim numerem. Podmieniamy
    tylko wtedy, gdy numer wypada poza kolejnością, a jego początek mieści się
    dokładnie między sąsiadami — na 5804 artykułach dwunastu aktów taki
    przypadek jest jeden, więc warunek jest wąski, a nie zgadywanie.
    """
    bazy = [int(re.match(r'(\d+)', n).group(1)) for n, *_ in jedn]
    for i in range(1, len(jedn) - 1):
        if bazy[i - 1] < bazy[i] < bazy[i + 1]:
            continue
        m = re.fullmatch(r'(\d+)', jedn[i][0])
        if not m:
            continue
        cyfry = m.group(1)
        for k in range(1, len(cyfry)):
            if bazy[i - 1] < int(cyfry[:k]) < bazy[i + 1]:
                _zlepki[(key, cyfry[:k])] = cyfry
                jedn[i] = (cyfry[:k],) + jedn[i][1:]
                break
    return jedn


def extract_pl_article_html(key: str, raw_html: str, art: str,
                            ustep: str | None) -> str | None:
    """Wycina artykuł po znacznikach jednostek redakcyjnych źródła.

    Pewniejsze niż szukanie nagłówka „Art. N." w tekście: nie łapie spisu
    treści ani odesłań i nie wymaga zgadywania, gdzie kończy się akt.

    Osobno rozstrzyga przypadek, w którym tekst jednolity drukuje DWA brzmienia
    tego samego artykułu. O tym, które obowiązuje, decyduje data z odnośnika, a
    nie kolejność druku ani długość wycinka — bo tekst jednolity zamraża stan
    prawny na dzień obwieszczenia, a nowelizacja mogła wejść w życie później.
    Art. 479(45) k.p.c.: drugie brzemienie („uchylony") obowiązuje od
    18.04.2026, więc pierwsze jest dziś nieaktualne. Art. 10 i 24 u.ś.u.d.e.
    oraz art. 3b i 25 u.ś.u.d.e.: drugie brzmienie obowiązuje od 10.11.2024
    (wejście w życie Prawa komunikacji elektronicznej), a tekst jednolity jest
    z 10.10.2024 — miesiąc wcześniej.
    """
    klucz = _kanon_art(art)
    if not klucz:
        return None
    trafienia = [(t, d) for n, t, d in _jednostki_html(key, raw_html) if n == klucz]
    if not trafienia:
        return None

    dzis = _dt.date.today()
    wybor, nieznane = 0, False
    if len(trafienia) > 1:
        for i, (_, data) in enumerate(trafienia[1:], start=1):
            if data is None:
                nieznane = True
            elif data <= dzis:
                wybor = i
    tekst, data_wyboru = trafienia[wybor]
    if not _wiarygodny(tekst):
        return None
    if ustep:
        tekst = _cut_ustep(tekst, ustep)
        if not tekst:
            return None

    zlepek = _zlepki.get((key, klucz))
    if zlepek:
        tekst += (f"\n\n⚠ Źródło drukuje numer tego artykułu zlepiony z numerem "
                  f"odnośnika („Art. {zlepek}.”). Powyżej treść art. {klucz} "
                  f"— numer odczytany z kolejności artykułów w akcie.")
    if len(trafienia) > 1:
        tekst += f"\n\n⚠ Tekst jednolity drukuje {len(trafienia)} brzmienia tego artykułu. "
        tekst += (f"Powyżej brzmienie obowiązujące od {data_wyboru:%d.%m.%Y}."
                  if data_wyboru else
                  "Powyżej brzmienie obowiązujące w dniu tego tekstu jednolitego.")
        przyszle = [d for _, d in trafienia if d and d > dzis]
        if przyszle:
            tekst += (" Kolejne wchodzi w życie "
                      + ", ".join(f"{d:%d.%m.%Y}" for d in sorted(przyszle)) + ".")
        if nieznane:
            tekst += (" Przy co najmniej jednym brzmieniu nie udało się odczytać daty "
                      "wejścia w życie z odnośnika — sprawdź odnośniki w Dz.U.")
    return tekst



def extract_pl_article(text: str, art: str, ustep: str | None) -> str | None:
    frag = _art_regex(art)
    # Nagłówek artykułu zaczyna się WIELKĄ literą („Art. 1."); małe „art. 1."
    # to odesłanie wewnątrz zdania. Bez tego rozróżnienia re.search trafiał
    # w pierwsze odesłanie zamiast w przepis.
    kand = []
    # Granica końca musi być jednostką TEJ SAMEJ rangi co początek: artykuł
    # kończy się na następnym artykule, nie na własnym paragrafie.
    for prefix, granica in ((rf'Art\.\s*{frag}\s*\.', r'\bArt\.\s*\d+'),
                            (rf'§\s*{frag}\s*\.', r'§\s*\d+')):
        for m in re.finditer(prefix, text):
            nxt = re.search(granica, text[m.end():])
            end = m.end() + nxt.start() if nxt else min(m.start() + 4000, len(text))
            kand.append((end - m.start(), m.start(), end))
        if kand:
            break
    if not kand:
        return None
    # Odrzuć kandydatów spoza trzonu aktu — także gdy jest tylko jeden.
    # Kodeks pracy nie ma art. 19; jedyne „Art. 19." w pliku stoi w bloku
    # przejściowym, więc poprawną odpowiedzią jest odmowa, nie cudzy przepis.
    lo, hi = _trzon_aktu(text)
    if hi > lo:
        w_trzonie = [k for k in kand if lo <= k[1] <= hi]
        if w_trzonie or _trzon_wiarygodny(text):
            kand = w_trzonie
    if not kand:
        return None
    if len(kand) > 1:
        kand = _wybierz_po_sasiadach(text, art, kand)
    # Gdy sąsiedzi nie rozstrzygają, bierzemy wycinek z najdłuższą treścią —
    # odesłanie i pozycja spisu treści urywają się po kilku znakach.
    _, start, end = max(kand)
    art_text = text[start:end].strip()
    if not _wiarygodny(art_text):
        return None
    return _cut_ustep(art_text, ustep) if ustep else art_text


def extract_eu_article(text: str, art: str, ustep: str | None) -> str | None:
    m = re.search(rf'\bArtykuł\s+{re.escape(art)}\b', text, re.IGNORECASE)
    if not m:
        return None
    nxt = re.search(r'\bArtykuł\s+\d+\b', text[m.end():], re.IGNORECASE)
    end = m.end() + nxt.start() if nxt else min(m.start() + 5000, len(text))
    art_text = text[m.start():end].strip()
    return _cut_ustep(art_text, ustep) if ustep else art_text


def _podstawa_tekstu(info: dict) -> str:
    """Opis tekstu jednolitego, na którym oparta jest odpowiedź.

    Narzędzie deklaruje aktualne brzmienie, a najnowszych tekstów jednolitych
    nie ma w HTML — od 2025 r. API ELI daje dla Dz.U. wyłącznie PDF — więc
    sięgamy po starszy. Bez tej informacji użytkownik dostaje nieaktualne
    brzmienie opatrzone znacznikiem weryfikacji.
    """
    zr = _zrodlo.get(f"PL:{info['pub']}:{info['year']}:{info['pos']}")
    if not zr or len(zr) != 3:
        return ""
    ident, data, po = zr
    if not data:
        return f"\n(tekst jednolity {ident})"
    opis = f"\n(tekst jednolity {ident} z {data}"
    if po:
        opis += f"; **po tej dacie weszło {po} nowelizacji** — sprawdź aktualność"
    return opis + ")"


async def verify_article(citation: str) -> str:
    """Zwraca dokładne brzmienie cytowanego przepisu ze źródła oficjalnego.
    Format: 'art. N [ust. M] KOD' (np. 'art. 45 u.k.k.', 'art. 28 ust. 3 RODO')."""
    parsed = parse_citation(citation)
    if not parsed:
        return (f"❌ Nierozpoznany format: '{citation}'\n"
                f"Użyj: 'art. N [ust. M] KOD' — np. 'art. 45 u.k.k.'\n"
                f"Lista kodów: list_acts().")
    act, art, ustep = parsed["act"], parsed["art"], parsed["ustep"]
    ref = f"art. {art}" + (f" ust. {ustep}" if ustep else "")
    pl_key = _resolve(act, PL_ACTS)
    eu_key = _resolve(act, EU_ACTS)

    if pl_key:
        info = PL_ACTS[pl_key]
        try:
            text = await _fetch_pl(info)
        except httpx.TimeoutException:
            return f"❌ Timeout pobierania {info['name']} z api.sejm.gov.pl"
        if text is None:
            return f"❌ Nie udało się pobrać {info['name']} (sieć/ELI)"
        key = _klucz_pl(info)
        raw = _html_cache.get(key)
        result = extract_pl_article_html(key, raw, art, ustep) if raw else None
        if result is None:
            result = extract_pl_article(text, art, ustep)
        if not result:
            return f"❌ {ref} nie znaleziony w {info['name']}. Sprawdź numer artykułu."
        podstawa = _podstawa_tekstu(info)
        return (f"📜 **{info['name']}**, {ref}\n(źródło: api.sejm.gov.pl)"
                f"{podstawa}\n\n{result}")

    if eu_key:
        info = EU_ACTS[eu_key]
        try:
            text = await _fetch_eu(info)
        except httpx.TimeoutException:
            return f"❌ Timeout pobierania {info['name']} z EUR-Lex"
        if text is None:
            return f"❌ Nie udało się pobrać {info['name']} z EUR-Lex"
        result = extract_eu_article(text, art, ustep)
        if not result:
            return f"❌ {ref} nie znaleziony w {info['name']}. Sprawdź numer artykułu."
        skad = (_zrodlo.get(f"EU:{info['celex']}") or ("EUR-Lex",))[0]
        return (f"📜 **{info['name']}**, {ref}\n"
                f"(źródło: {skad}, CELEX {info['celex']}, wersja polska)\n\n{result}")

    known = ", ".join(dict.fromkeys(list(PL_ACTS) + list(EU_ACTS)))
    return f"❌ Nieznany kod aktu: '{act}'\nObsługiwane: {known}"


def list_acts() -> str:
    """Lista obsługiwanych kodów aktów z pełnymi nazwami."""
    pl = "\n".join(f"  {k:<16} → {v['name']}" for k, v in PL_ACTS.items())
    eu = "\n".join(f"  {k:<16} → {v['name']}" for k, v in EU_ACTS.items())
    return ("📚 Obsługiwane kody aktów\n\n"
            f"Prawo PL (api.sejm.gov.pl):\n{pl}\n\n"
            f"Prawo UE (EUR-Lex, PL):\n{eu}")
