"""legal-cite — logika weryfikacji brzmienia przepisu z OFICJALNEGO źródła.

Pobiera dokładny tekst cytowanego artykułu (api.sejm.gov.pl dla prawa PL,
EUR-Lex dla prawa UE) i zwraca TYLKO ten artykuł — nie cały akt. Akty są
cache'owane w obrębie sesji procesu. AKTUALNE brzmienie (tekst jednolity),
nie pierwotne z dnia ogłoszenia.
"""
from __future__ import annotations

import bisect
import contextvars
import datetime as _dt
import html as _html
import re
import time
from urllib.parse import quote as _quote

import logging
import httpx

# Dzień, na który wybierane jest brzmienie (verify_article z na_dzien); domyślnie dziś.
_NA_DZIEN: contextvars.ContextVar[_dt.date | None] = contextvars.ContextVar("na_dzien", default=None)


def _dzis() -> _dt.date:
    return _NA_DZIEN.get() or _dt.date.today()


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
    "KRO":      dict(pub="DU", year=1964, pos=59,   name="Kodeks rodzinny i opiekuńczy"),
    "KRiO":     dict(pub="DU", year=1964, pos=59,   name="Kodeks rodzinny i opiekuńczy"),
    "u.k.s.c.": dict(pub="DU", year=2005, pos=1398, name="Ustawa o kosztach sądowych w sprawach cywilnych"),
    "UKSC":     dict(pub="DU", year=2005, pos=1398, name="Ustawa o kosztach sądowych w sprawach cywilnych"),
    # księgi wieczyste, karne i administracyjne (pozycje sprawdzone w ELI 2026-10-18).
    # Konstytucja: tekstu jednolitego w Dz.U. nie ma, PDF pierwotny z 1997 r. nie ma zmian
    # z 2006 i 2009 — źródłem jest tekst ujednolicony Kancelarii Sejmu z ELI (plik typu „U”),
    # nieurzędowy, z kontrolą warstwy tekstowej i sprawdzeniem, że obejmuje akty zmieniające.
    "Konstytucja": dict(pub="DU", year=1997, pos=483, name="Konstytucja Rzeczypospolitej Polskiej", tekst_u="D19970483Lj.pdf"),
    "Konstytucji": dict(pub="DU", year=1997, pos=483, name="Konstytucja Rzeczypospolitej Polskiej", tekst_u="D19970483Lj.pdf"),
    "Konstytucja RP": dict(pub="DU", year=1997, pos=483, name="Konstytucja Rzeczypospolitej Polskiej", tekst_u="D19970483Lj.pdf"),
    "Konstytucji RP": dict(pub="DU", year=1997, pos=483, name="Konstytucja Rzeczypospolitej Polskiej", tekst_u="D19970483Lj.pdf"),
    "u.k.w.h.": dict(pub="DU", year=1982, pos=147,  name="Ustawa o księgach wieczystych i hipotece"),
    "u.m.w.p.": dict(pub="DU", year=2002, pos=1679, name="Ustawa o minimalnym wynagrodzeniu za pracę"),
    # AML (sprawdzone w ELI 2026-10-28)
    "AML":      dict(pub="DU", year=2018, pos=723,  name="Ustawa o przeciwdziałaniu praniu pieniędzy oraz finansowaniu terroryzmu"),
    "u.p.p.p.f.t.": dict(pub="DU", year=2018, pos=723, name="Ustawa o przeciwdziałaniu praniu pieniędzy oraz finansowaniu terroryzmu"),
    "ustawy AML": dict(pub="DU", year=2018, pos=723, name="Ustawa o przeciwdziałaniu praniu pieniędzy oraz finansowaniu terroryzmu"),
    "ustawy o przeciwdziałaniu praniu pieniędzy oraz finansowaniu terroryzmu": dict(pub="DU", year=2018, pos=723, name="Ustawa o przeciwdziałaniu praniu pieniędzy oraz finansowaniu terroryzmu"),
    "ustawy o minimalnym wynagrodzeniu za pracę": dict(pub="DU", year=2002, pos=1679, name="Ustawa o minimalnym wynagrodzeniu za pracę"),
    "u.c.":     dict(pub="DU", year=2013, pos=1650, name="Ustawa o cudzoziemcach"),
    "ustawy o cudzoziemcach": dict(pub="DU", year=2013, pos=1650, name="Ustawa o cudzoziemcach"),
    # nabywanie nieruchomości przez cudzoziemców: akt pierwotny Dz.U. 1920 nr 31 poz. 178 (ELI DU/1920/178),
    # t.j. Dz.U. 2017 poz. 2278 (HTML); nowela Dz.U. 2026 poz. 1099 w życie 19.11.2026 (sprawdzone w ELI 2026-10-24)
    # Regulamin Sejmu: uchwała w Monitorze Polskim (MP/1992/185), t.j. tylko w PDF
    "Regulamin Sejmu":   dict(pub="MP", year=1992, pos=185, name="Regulamin Sejmu Rzeczypospolitej Polskiej"),
    "Regulaminu Sejmu":  dict(pub="MP", year=1992, pos=185, name="Regulamin Sejmu Rzeczypospolitej Polskiej"),
    "r.S.":              dict(pub="MP", year=1992, pos=185, name="Regulamin Sejmu Rzeczypospolitej Polskiej"),
    "UNNC":     dict(pub="DU", year=1920, pos=178,  name="Ustawa o nabywaniu nieruchomości przez cudzoziemców"),
    "u.n.n.c.": dict(pub="DU", year=1920, pos=178,  name="Ustawa o nabywaniu nieruchomości przez cudzoziemców"),
    "ustawy o nabywaniu nieruchomości przez cudzoziemców": dict(pub="DU", year=1920, pos=178, name="Ustawa o nabywaniu nieruchomości przez cudzoziemców"),
    "KW":      dict(pub="DU", year=1971, pos=114,  name="Kodeks wykroczeń"),
    "KPK":      dict(pub="DU", year=1997, pos=555,  name="Kodeks postępowania karnego"),
    "KKS":      dict(pub="DU", year=1999, pos=930,  name="Kodeks karny skarbowy"),
    "KKW":      dict(pub="DU", year=1997, pos=557,  name="Kodeks karny wykonawczy"),
    "KPA":      dict(pub="DU", year=1960, pos=168,  name="Kodeks postępowania administracyjnego"),
    "PPSA":     dict(pub="DU", year=2002, pos=1270, name="Prawo o postępowaniu przed sądami administracyjnymi"),
    # podatkowe i majątkowe
    "O.p.":     dict(pub="DU", year=1997, pos=926,  name="Ordynacja podatkowa"),
    "Ordynacja podatkowa": dict(pub="DU", year=1997, pos=926, name="Ordynacja podatkowa"),
    "Ordynacji podatkowej": dict(pub="DU", year=1997, pos=926, name="Ordynacja podatkowa"),
    "u.p.d.o.f.": dict(pub="DU", year=1991, pos=350, name="Ustawa o podatku dochodowym od osób fizycznych (PIT)"),
    "PIT":      dict(pub="DU", year=1991, pos=350,  name="Ustawa o podatku dochodowym od osób fizycznych (PIT)"),
    "ustawy o PIT": dict(pub="DU", year=1991, pos=350, name="Ustawa o podatku dochodowym od osób fizycznych (PIT)"),
    "u.p.d.o.p.": dict(pub="DU", year=1992, pos=86, name="Ustawa o podatku dochodowym od osób prawnych (CIT)"),
    "CIT":      dict(pub="DU", year=1992, pos=86,   name="Ustawa o podatku dochodowym od osób prawnych (CIT)"),
    "ustawy o CIT": dict(pub="DU", year=1992, pos=86, name="Ustawa o podatku dochodowym od osób prawnych (CIT)"),
    "u.f.r.":   dict(pub="DU", year=2023, pos=326,  name="Ustawa o fundacji rodzinnej"),
    "ustawy o fundacji rodzinnej": dict(pub="DU", year=2023, pos=326, name="Ustawa o fundacji rodzinnej"),
    "u.p.s.d.": dict(pub="DU", year=1983, pos=207,  name="Ustawa o podatku od spadków i darowizn"),
    "ustawy o podatku od spadkow i darowizn": dict(pub="DU", year=1983, pos=207, name="Ustawa o podatku od spadków i darowizn"),
    "u.KRS":    dict(pub="DU", year=1997, pos=769,  name="Ustawa o Krajowym Rejestrze Sądowym"),
    "ustawy o KRS": dict(pub="DU", year=1997, pos=769, name="Ustawa o Krajowym Rejestrze Sądowym"),
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
    if norm in idx:
        return idx[norm]
    # kropki i odstępy wewnątrz skrótu: k.p.c. / k. p. c. → KPC, u.k.s.c → UKSC
    zwarty = re.sub(r'[.\s]', '', act.lower())
    idx2 = {re.sub(r'[.\s]', '', k.lower()): k for k in table}
    return idx2.get(zwarty)


_SUP = str.maketrans("¹²³⁴⁵⁶⁷⁸⁹⁰", "1234567890")


# litery modyfikujące Unicode używane w indeksach numerów (131¹ᵃ, 479³⁰ᶠ)
_SUP_LIT = "ᵃᵇᶜᵈᵉᶠᵍʰⁱʲᵏˡᵐⁿᵒᵖʳˢᵗᵘᵛʷˣʸᶻ"
_SUP_ALL = "¹²³⁴⁵⁶⁷⁸⁹⁰" + _SUP_LIT


def _indeks_na_nawias(raw: str) -> str:
    """„131¹ᵃ” → „131[1a]”: indeks górny (cyfry i litery) na zapis nawiasowy,
    który rozumie reszta parsera."""
    import unicodedata
    return re.sub(rf'([{_SUP_ALL}]+)',
                  lambda m: '[' + unicodedata.normalize('NFKC', m.group(1)) + ']', raw)


def parse_citation(raw: str) -> dict | None:
    """Parsuje cytat: 'art. N[a][¹] [ust./§ M] [pkt/lit. X] KOD' → {art, ustep, act}.
    Obsługuje sufiks literowy, także kilkuliterowy (36a, 59aa), indeks górny
    (385¹/385[1]/385(1)) i § jako jednostkę redakcyjną (KC numeruje paragrafami)."""
    m = re.match(
        r'(?:art\.|§)\s*'
        r'(\d+[a-z]*(?:\s*(?:[¹²³⁴⁵⁶⁷⁸⁹]+|\[\d+[a-z]*\]|\(\d+[a-z]*\)|\^\d+))?)\s*'  # numer art. (36a, 59aa) + opc. indeks (385¹, 18[3d])
        r'(?:(?:ust\.|§)\s*(\d+[a-z]*(?:\s*(?:\[\d+[a-z]*\]|\(\d+[a-z]*\)|\^\d+))?))?\s*'  # ustęp ALBO paragraf, też § 1¹ / § 2[1]
        r'(?:(?:pkt|lit\.)\s*\S+\s*)?(.+)',                               # pkt/lit ignorowane; kod aktu
        _indeks_na_nawias(raw.strip()), re.IGNORECASE,
    )
    if not m:
        return None
    ustep = m.group(2)
    if ustep:
        # jeden zapis indeksu dla reszty parsera: 1(1) / 1^1 / 1 [1] → 1[1]
        ustep = re.sub(r'\s*(?:\[(\w+)\]|\((\w+)\)|\^(\w+))',
                       lambda x: f"[{x.group(1) or x.group(2) or x.group(3)}]", ustep)
    return {
        "art": m.group(1).strip(),
        "ustep": ustep,
        "act": m.group(3).strip().rstrip('.').strip(),
    }


def _art_regex(raw_art: str) -> str:
    """Buduje fragment regex dopasowujący numer artykułu w tekście źródła,
    tolerancyjnie na spacje. 385¹→'385\\s+1' (źródło: „Art. 385 1 ."),
    36a→'36\\s*a', 59aa→'59\\s*aa', 45→'45', 131¹ᵃ/131[1a]→'131\\s+1\\s*a'.

    Indeks z literą musi zostać w wzorcu: wcześniej „131[1a]” dawało samo
    '131', więc ścieżka zapasowa oddawała art. 131 jako art. 131¹ᵃ — w trybie
    na_dzien przy t.j. sprzed dodania jednostki (#11). Numer, którego nie da
    się rozpoznać, daje wzorzec niedopasowujący niczego zamiast gołej bazy."""
    s = _indeks_na_nawias(raw_art.strip())                    # 131¹ᵃ → 131[1a]
    s = re.sub(r'\s*[\(\^]\s*(\d+[a-z]*)\s*\)?', r'[\1]', s)   # 131(1a) / 131^1 → 131[1a]
    s = re.sub(r'\s+', '', s).lower()
    m = re.fullmatch(r'(\d+)([a-z]*)(?:\[(\d+)([a-z]*)\])?', s)
    if not m:
        return r'(?!)'
    baza = m.group(1) + (rf'\s*{m.group(2)}' if m.group(2) else '')
    if not m.group(3):
        return baza
    return baza + rf'\s+{m.group(3)}' + (rf'\s*{m.group(4)}' if m.group(4) else '')


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


_tj_cache: dict[str, tuple[float, list[dict]]] = {}
# Lista tekstów jednolitych jest ważna 6 godzin: nowy t.j. ogłoszony w tym
# czasie musi się pojawić bez restartu instancji (przy stale włączonej
# instancji restart bywa rzadki). Wynik z awarią API nie jest zapamiętywany.
_TJ_TTL = 6 * 3600


async def _teksty_jednolite(info: dict) -> list[dict]:
    """Teksty jednolite aktu od najnowszego, z informacją, czy API daje HTML.

    Kolejność ustala numer pozycji w Dz.U., nie kolejność z metadanych. Każdy
    wpis: {id, html (bool), html_text, meta}. Wpisy sprawdzane są po kolei
    aż do pierwszego z HTML — starsze nie są potrzebne. Od 2025 r. API ELI
    nie publikuje HTML dla Dz.U., więc najnowszy wpis bywa tylko w PDF, a
    pierwszy z HTML jest o rok lub dwa starszy. Na końcu listy oryginał aktu.
    """
    key = _klucz_pl(info)
    if key in _tj_cache and time.monotonic() - _tj_cache[key][0] < _TJ_TTL:
        return _tj_cache[key][1]
    base = "https://api.sejm.gov.pl/eli/acts"
    out: list[dict] = []
    awaria = False
    async with httpx.AsyncClient(follow_redirects=True, timeout=25, headers=_HEADERS) as c:
        idents: list[str] = []
        zmieniajace: list[dict] = []
        try:
            meta = (await c.get(f"{base}/{info['pub']}/{info['year']}/{info['pos']}")).json()
            for ent in (meta.get("references") or {}).get("Inf. o tekście jednolitym", []):
                parts = (ent.get("id") or "").split("/")
                if len(parts) == 3 and parts[1].isdigit() and parts[2].isdigit():
                    idents.append("/".join(parts))
            zmieniajace = (meta.get("references") or {}).get("Akty zmieniające", [])
        except Exception:
            pass
        idents = sorted(set(idents), key=lambda s: (int(s.split("/")[1]), int(s.split("/")[2])),
                        reverse=True)[:4]
        idents.append(f"{info['pub']}/{info['year']}/{info['pos']}")  # fallback: oryginał
        for ident in idents:
            wpis = {"id": ident, "html": False, "html_text": None, "meta": {},
                    "zmieniajace": zmieniajace, "html_awaria": False}
            try:
                wpis["meta"] = (await c.get(f"{base}/{ident}")).json()
            except Exception:
                awaria = True
            # HTML istnieje tylko, gdy metadane tak mówią (textHTML); 5xx albo błąd
            # sieci przy takim akcie to awaria API, nie brak HTML
            try:
                resp = await c.get(f"{base}/{ident}/text.html")
                if resp.status_code == 200 and len(resp.text) > 3000 \
                        and len(_strip_html(resp.text)) > 1500:
                    wpis["html"], wpis["html_text"] = True, resp.text
                elif resp.status_code >= 500 and wpis["meta"].get("textHTML"):
                    wpis["html_awaria"] = awaria = True
            except Exception:
                if wpis["meta"].get("textHTML"):
                    wpis["html_awaria"] = awaria = True
            out.append(wpis)
            if wpis["html"]:
                break
    if awaria:
        logger.warning("api eli awaria przy %s — lista t.j. nie trafia do cache", key)
    else:
        _tj_cache[key] = (time.monotonic(), out)
    return out


def _nowelizacje_po(zmieniajace: list[dict], data: str,
                    dzis: _dt.date | None = None) -> tuple[list, list]:
    """Akty zmieniające z datą po dacie t.j., rozdzielone na te, które weszły
    w życie (data <= dziś), i oczekujące (data w przyszłości). Pole date
    w wykazie ELI to data wejścia w życie zmiany tego aktu — dla Dz.U. 2026
    poz. 507 przy k.c. 1.11.2028, więc liczenie bez daty dzisiejszej pisało
    przy każdym artykule k.c. „weszła w życie 1 nowelizacja”.
    Zwraca dwie listy (id, data ISO) posortowane po dacie."""
    if not data:
        return [], []
    dzis_iso = (dzis or _dt.date.today()).isoformat()
    po = sorted(((e.get("id") or "?", e.get("date") or "") for e in zmieniajace
                 if (e.get("date") or "") > data), key=lambda x: (x[1], x[0]))
    return [x for x in po if x[1] <= dzis_iso], [x for x in po if x[1] > dzis_iso]


def _adres_dz_u(ident: str) -> str:
    """„DU/2026/507” → „Dz.U. 2026 poz. 507”."""
    cz = ident.split("/")
    if len(cz) == 3 and cz[0] in ("DU", "MP"):
        return f"{'Dz.U.' if cz[0] == 'DU' else 'M.P.'} {cz[1]} poz. {cz[2]}"
    return ident


def _data_pl(iso: str) -> str:
    try:
        return f"{_dt.date.fromisoformat(iso):%d.%m.%Y}"
    except ValueError:
        return iso or "data nieznana"


def _lista_nowelizacji(akty: list, maks: int = 8) -> str:
    opis = ", ".join(f"{_adres_dz_u(i)} ({_data_pl(d)})" for i, d in akty[:maks])
    return opis + (f" i {len(akty) - maks} innych" if len(akty) > maks else "")


def _aktualnosc_pl(zmieniajace: list[dict], data_tj: str) -> tuple[str, str, str]:
    """Linia „Aktualność”, kod dla modelu i pola z identyfikatorami aktów.

    Lista zamiast licznika: model może zacytować i sprawdzić konkretny akt.
    Nowelizacje oczekujące są osobno — nie zmieniają dzisiejszego brzmienia,
    ale zmienią je w podanym dniu (umowy, terminy)."""
    weszle, oczekujace = _nowelizacje_po(zmieniajace, data_tj)
    if weszle:
        n = len(weszle)
        czas = ("weszła" if n == 1 else
                "weszły" if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14 else "weszło")
        tekst = (f"nieustalona — po dacie tego t.j. ({data_tj}) {czas} w życie "
                 f"{_odmiana_nowelizacji(n)}: {_lista_nowelizacji(weszle)}; "
                 f"sprawdź, czy dotyczy to tego artykułu")
        kod = f"nieustalona_{len(weszle)}_nowelizacji_po_tj"
    else:
        tekst = (f"wg wykazu aktów zmieniających w API ELI po dacie tego t.j. "
                 f"({data_tj}) nie weszła w życie żadna nowelizacja")
        kod = "potwierdzona_wg_wykazu_eli"
    if oczekujace:
        tekst += (f". Oczekuje (jeszcze nie obowiązuje, data wg wykazu ELI): "
                  f"{_lista_nowelizacji(oczekujace)}")
    pola = ("; nowelizacje_po_tj=" + (",".join(f"{i}@{d}" for i, d in weszle) or "brak")
            + "; nowelizacje_oczekujace=" + (",".join(f"{i}@{d}" for i, d in oczekujace) or "brak"))
    return tekst, kod, pola


async def _fetch_pl(info: dict) -> str | None:
    """Pobiera tekst aktu z najnowszego tekstu jednolitego, który API daje w
    HTML (nie pierwotny z dnia ogłoszenia: `/text.html` pod pozycją oryginału
    zwraca brzmienie z 1964 r.). Gdy najnowszy t.j. jest tylko w PDF, ten
    HTML jest starszy — o tym decyduje verify_article, nie ta funkcja."""
    key = _klucz_pl(info)
    if key in _cache:
        return _cache[key]
    for wpis in await _teksty_jednolite(info):
        if not wpis["html"]:
            continue
        text = _strip_html(wpis["html_text"])
        _cache[key] = text
        _html_cache[key] = wpis["html_text"]
        data = wpis["meta"].get("announcementDate") or ""
        _zrodlo[key] = (wpis["id"], data, wpis["zmieniajace"])
        return text
    return None


_SPARQL = "https://publications.europa.eu/webapi/rdf/sparql"
# CELEX → (czas, wersja); tylko udane odpytania — awaria SPARQL nie jest
# zapamiętywana, żeby chwilowy błąd nie przypiął tekstu pierwotnego na stałe
_wersje_eu: dict[str, tuple[float, dict]] = {}
_WERSJE_EU_TTL = 6 * 3600


async def _sparql(zapytanie: str) -> list[dict]:
    # jedno ponowienie: endpoint Urzędu Publikacji miewa pojedyncze odmowy
    async with httpx.AsyncClient(timeout=30, headers={
            **_HEADERS, "Accept": "application/sparql-results+json"}) as c:
        for proba in range(2):
            try:
                resp = await c.get(_SPARQL, params={"query": zapytanie})
                resp.raise_for_status()
                break
            except httpx.HTTPError:
                if proba:
                    raise
    return [{k: v["value"] for k, v in b.items()}
            for b in resp.json()["results"]["bindings"]]


async def _wersja_eu(celex: str, dzien: _dt.date | None = None) -> dict:
    """Ustala, z której wersji aktu UE cytować — na dziś albo na wskazany dzień.

    CELEX 3… to tekst pierwotny z Dz.U. UE — bez późniejszych zmian (AI Act:
    brak art. 111 ust. 4 dodanego rozporządzeniem 2026/1744). Wersje
    skonsolidowane mają CELEX 0…-RRRRMMDD (data, od której obowiązuje dana
    wersja). Bierzemy najnowszą obowiązującą w danym dniu i osobno wypisujemy
    akty zmieniające, które weszły w życie po jej dacie — konsolidacja bywa
    spóźniona względem zmian.
    """
    dzien = dzien or _dt.date.today()
    teraz = time.time()
    if celex in _wersje_eu and teraz - _wersje_eu[celex][0] < _WERSJE_EU_TTL:
        surowe = _wersje_eu[celex][1]
    else:
        prefiks = "0" + celex[1:] + "-"
        try:
            kons = await _sparql(
                "PREFIX cdm: <http://publications.europa.eu/ontology/cdm#>\n"
                "SELECT DISTINCT ?celex WHERE { ?w cdm:resource_legal_id_celex ?celex . "
                f'FILTER(STRSTARTS(STR(?celex), "{prefiks}")) }}')
            zmiany = await _sparql(
                "PREFIX cdm: <http://publications.europa.eu/ontology/cdm#>\n"
                "SELECT DISTINCT ?celex ?eif WHERE { ?a cdm:resource_legal_amends_resource_legal ?b . "
                f'?b cdm:resource_legal_id_celex ?bc . FILTER(STR(?bc) = "{celex}") '
                "?a cdm:resource_legal_id_celex ?celex . "
                "OPTIONAL { ?a cdm:resource_legal_date_entry-into-force ?eif } }")
        except (httpx.HTTPError, KeyError, ValueError) as e:
            logger.info("sparql celex=%s blad=%s", celex, type(e).__name__)
            return {"celex": celex, "data": None, "blad": True, "zmieniajace": []}
        wersje = []
        for k in kons:
            m = re.fullmatch(re.escape(prefiks) + r"(\d{8})", k["celex"])
            if m:
                wersje.append((_dt.datetime.strptime(m.group(1), "%Y%m%d").date(), k["celex"]))
        zmieniajace = []
        for z in zmiany:
            try:
                eif = _dt.date.fromisoformat(z.get("eif", "")[:10])
            except ValueError:
                eif = None
            zmieniajace.append((z["celex"], eif))
        surowe = {"wersje": sorted(set(wersje)),
                  "zmieniajace": sorted(set(zmieniajace),
                                        key=lambda x: (x[1] or _dt.date.max, x[0]))}
        _wersje_eu[celex] = (teraz, surowe)
    daty = [w for w in surowe["wersje"] if w[0] <= dzien]
    data, wybrany = max(daty) if daty else (None, celex)
    nastepna = next((d for d, _ in surowe["wersje"] if d > dzien), None)
    return {"celex": wybrany, "data": data, "blad": False, "nastepna": nastepna,
            "zmieniajace": surowe["zmieniajace"]}


# znaczniki tekstu skonsolidowanego: ▼B / ►M1 … ◄ (B = akt podstawowy,
# M = akt zmieniający, A = akt przystąpienia, C = sprostowanie)
_ZNACZNIK_EU_RE = re.compile(r'[►▼]\s?([BMAC]\d*)\b\s?|\s?◄')


def _legenda_zmian(tekst: str) -> dict[str, str]:
    """„►M1 ROZPORZĄDZENIE … (UE) 2026/1744 z dnia 8 lipca 2026 r.” z nagłówka
    tekstu skonsolidowanego → {"M1": opis}."""
    glowa = tekst[:tekst.find("▼B")] if "▼B" in tekst else tekst[:5000]
    legenda = {m.group(1): re.sub(r'\s+', ' ', m.group(2)).strip()
               for m in re.finditer(r'►([MA]\d+)\s+(.{10,300}?\bz dnia \d{1,2} \S+ \d{4} r\.)', glowa)}
    # „►C1 Sprostowanie, Dz.U. L 127, 23.5.2018, s. 2 (2016/679)”
    legenda.update({m.group(1): m.group(2).strip()
                    for m in re.finditer(r'►(C\d+)\s+(Sprostowanie,[^►▼]{5,120}?\(\d{2,4}/\d+\))', glowa)})
    return legenda


async def _fetch_eu(info: dict) -> str | None:
    """Pobiera polski tekst aktu UE — najpierw z CELLAR, potem z EUR-Lex.

    Publiczna strona EUR-Lex stoi za WAF-em, który odpowiada 202 zamiast
    treści. Blokada nie jest stała: na tym samym kliencie potrafi włączyć się
    w ciągu dnia, więc nie da się jej obejść retrajem ani nagłówkiem. CELLAR
    to interfejs maszynowy Urzędu Publikacji z negocjacją treści — ten sam
    dokument, bez bramki dla przeglądarek (najpierw XHTML, potem HTML starego
    formatu — jedyny tekst aktów z polskiego wydania specjalnego). `info['celex']` może być CELEX-em
    wersji skonsolidowanej (0…-RRRRMMDD).
    """
    key = f"EU:{info['celex']}"
    if key in _cache:
        return _cache[key]

    zrodla = (
        ("CELLAR",
         f"http://publications.europa.eu/resource/celex/{_quote(info['celex'], safe='')}",
         {**_HEADERS, "Accept": "application/xhtml+xml", "Accept-Language": "pl"}),
        # akty sprzed 1.05.2004 r. z polskiego wydania specjalnego nie mają XHTML,
        # tylko HTML w starym formacie EUR-Lexu (pełny tekst polski) i PDF
        ("CELLAR",
         f"http://publications.europa.eu/resource/celex/{_quote(info['celex'], safe='')}",
         {**_HEADERS, "Accept": "text/html", "Accept-Language": "pl"}),
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
        # 202 = bramka WAF EUR-Lexu zwracająca stronę-wyzwanie zamiast aktu; próg długości
        # tylko dla EUR-Lexu — CELLAR nie ma WAF-u, a krótkie akty (rejestracja nazwy,
        # 6–7 tys. znaków) są prawdziwe
        prog = 10_000 if nazwa == "EUR-Lex" else 1_000
        if resp.status_code != 200 or len(resp.text) < prog:
            logger.info("zrodlo=%s celex=%s http=%s dlugosc=%s — probuje dalej",
                        nazwa, info["celex"], resp.status_code, len(resp.text))
            continue
        _cache[key] = _strip_html(resp.text)
        _zrodlo[key] = (nazwa,)
        return _cache[key]
    return None


# Nagłówek ustępu/paragrafu z opcjonalną literą i indeksem górnym. Źródła piszą
# indeks na trzy sposoby: HTML ELI „§ 1 1 .”, odczyt PDF „§ 1 1.”, druk 2026
# „§ 1[1].”, rzadziej wprost „§ 1¹.”. Lookbehind (?<!\d\s) nie pozwala wziąć
# samego indeksu („1.” w „§ 1 1.”) za początek jednostki.
_IDX_SUP = "[¹²³⁴⁵⁶⁷⁸⁹⁰ᵃᵇᶜᵈᵉᶠᵍʰⁱʲᵏˡᵐⁿᵒᵖʳˢᵗᵘᵛʷˣʸᶻ]+"
# Jednostka zaczyna się na początku tekstu albo po znaku kończącym zdanie lub punkt
# („. ”, „; ”, „: ”, „) ”) — „3.” w odesłaniu „w ust. 2 i 3.” to nie ustęp 3 (Konstytucja
# art. 55 ust. 1 urywał się na „w ust. 2 i”; zapytanie o ust. 3 mogło zacząć się w odesłaniu).
_POCZATEK_JEDN = r'(?:^|(?<=[.;:)\]”"]\s))'
_JEDN_USTEP_RE = re.compile(
    rf'{_POCZATEK_JEDN}(?:§\s*)?(?<![\d\w])(?<!\d\s)\d+[a-z]{{0,2}}'
    rf'(?:\s+\d+[a-z]?(?=\s?\.\s)|\s*\[\d+[a-z]?\]|{_IDX_SUP})?\s?\.\s')


def _cut_ustep(art_text: str, ustep: str) -> str | None:
    # ustęp „N." LUB paragraf „§ N." (KC); granica = następna jednostka tej samej
    # rangi — także z literą (1a) albo indeksem (§ 1¹), które wcześniej doklejały
    # się do poprzedniej jednostki („§ 1” art. 98 k.p.c. zabierał § 1¹ i § 1²)
    m = re.fullmatch(r'(\d+[a-z]*)(?:\[(\d+[a-z]*)\])?', ustep.strip())
    if not m:
        return None
    baza, idx = m.group(1), m.group(2)
    if idx:
        sup = idx.translate(str.maketrans("0123456789abcdefghijklmnoprstuvwxyz",
                                          "⁰¹²³⁴⁵⁶⁷⁸⁹ᵃᵇᶜᵈᵉᶠᵍʰⁱʲᵏˡᵐⁿᵒᵖʳˢᵗᵘᵛʷˣʸᶻ"))
        nr = (rf'{re.escape(baza)}(?:\s+{re.escape(idx)}|\s*\[{re.escape(idx)}\]'
              rf'|{re.escape(sup)})\s?\.\s')
    else:
        nr = rf'{re.escape(baza)}\.\s'
    # „(?<!Art\.\s)”: nagłówek „Art. 1.” nie jest ustępem 1 — bez tego „art. 1 ust. 1” aktu
    # o numeracji „Art. 1. 1. Nabycie…” (u.n.n.c.) oddawał samo „1.” (granica = następny ustęp)
    m = re.search(rf'{_POCZATEK_JEDN}(?:§\s*)?(?<![\d\w])(?<!\d\s)(?<!Art\.\s){nr}', art_text)
    if not m and baza == "1" and not idx:
        # ust. 1 aktu UE stoi zaraz po tytule artykułu („Artykuł 28 Podmiot
        # przetwarzający 1. Jeżeli…”), bez znaku przestankowego przed numerem
        m = re.search(rf'(?:§\s*)?(?<![\d\w])(?<!\d\s)(?<!Art\.\s){nr}', art_text)
    if not m:
        return None
    ust_start = m.start()
    nxt = _JEDN_USTEP_RE.search(art_text, m.end())
    ust_end = nxt.start() if nxt else len(art_text)
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
    if re.match(r'^\(\s*(?:uchylon|skreślon|skreslon|pominięt|pominiet|wygasł|wygasl|wygaśnięt|wygasniet)\w*\s*\)', body, re.IGNORECASE):
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
# rozporządzenie: jednostką główną jest paragraf („para_N”), artykułów nie ma
_UNIT_PARA_RE = re.compile(r'<div class="unit unit_para[^"]*" id="([^"]*)" data-id="para_([^"]+)"')
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
# numer odnośnika w <sup> — z dymkiem (w <a class="gloss-link">) albo goły
_SUP_NR_RE = re.compile(r'<sup>\s*(\d+)\s*\)\s*</sup>', re.IGNORECASE)
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


# Odnośnik przy ZDANIU, nie przy jednostce: „Zdanie pierwsze w tym brzmieniu obowiązuje
# do wejścia w życie zmiany, o której mowa w odnośniku 6.” — t.j. drukuje wtedy oba
# brzmienia zdania jedno po drugim w tym samym paragrafie (art. 505 k.p.k., Dz.U. 2026
# poz. 490: „Odpis wyroku…” i „Kopię wyroku…”, nowe od 1.10.2029). Wybór brzmienia działa
# na poziomie jednostek, nie zdań, więc taki tekst byłby oddany sklejony (#13).
_ZDANIE_DO_ZMIANY_RE = re.compile(
    r'(?i)^\s*zdani\w*\s+(\w+)\b.*?\bw tym brzmieniu obowiązuj\w*\s+do\s+(?:dnia\s+)?wejścia'
    r'.*?odnośniku\s+(\d+)')


def _wybierz_zdania_html(fragment: str, mapa: dict[str, str], dzis: _dt.date,
                        uwagi: list[str]) -> tuple[str, set[str]]:
    """Jak pdf_tj._wybierz_zdania, na HTML ELI: nowe brzmienie zdania (od początku
    odnośnika A do końca odnośnika B) wycinane, gdy jeszcze nie obowiązuje.
    Odnośnik B bywa gołym „<SUP>157)</SUP>” bez dymka — źródło linkuje treść
    przypisu tylko przy pierwszym użyciu (art. 505 k.p.k., t.j. 2024/37).
    Zwraca fragment i numery rozstrzygniętych odnośników A."""
    ok: set[str] = set()
    zamkniecie = re.compile(r'</a\s*>', re.IGNORECASE)
    for m in list(_PIERWSZY_ODNOSNIK_RE.finditer(fragment))[::-1]:
        z = _ZDANIE_DO_ZMIANY_RE.search(mapa.get(m.group(1)) or "")
        if not z:
            continue
        koniec_a = zamkniecie.search(fragment, m.end())
        if not koniec_a:
            continue
        nast = _SUP_NR_RE.search(fragment, koniec_a.end())  # następny odnośnik: z dymkiem albo goły
        if not nast or nast.group(1) != z.group(2):
            continue
        d = _data_wejscia(mapa, z.group(2))
        if d is None or d <= dzis:
            continue
        # Odnośnik ELI z dymkiem to <a class="gloss-link"><sup>N)</sup><span tooltip>…</span></A>,
        # a _strip_html usuwa go w całości do najbliższego </a> — cięcie w środku odnośnika
        # zjadało obowiązującą treść za nim (przegląd Astry, 28.10.2026).
        if re.search(r'<a\b[^>]*>\s*$', fragment[:nast.start()], re.IGNORECASE):
            koniec = zamkniecie.search(fragment, nast.end())
            if not koniec:
                continue
            kon = koniec.end()
        else:
            kon = nast.end()
        fragment = fragment[:m.start()] + " " + fragment[kon:]
        ok.add(m.group(1))
        uwagi.append(f"⚠ Zdanie {z.group(1)}: tekst jednolity drukuje dwa brzmienia; powyżej "
                     f"obowiązujące, nowe wchodzi w życie {d:%d.%m.%Y}.")
    return fragment, ok


def _zdania_dwa_brzmienia(mapa: dict[str, str], numery: list[str]) -> list[str]:
    """Opisy zdań wydrukowanych w dwóch brzmieniach (puste, gdy takich nie ma)."""
    out = []
    for nr in dict.fromkeys(numery):
        m = _ZDANIE_DO_ZMIANY_RE.search(mapa.get(nr) or "")
        if not m:
            continue
        d = _data_wejscia(mapa, m.group(2))
        out.append(f"zdanie {m.group(1)} wydrukowane w dwóch brzmieniach (odnośniki {nr} i "
                   f"{m.group(2)}; nowe " + (f"od {d:%d.%m.%Y}" if d else "z datą nieodczytaną")
                   + ") — narzędzie nie wybiera brzmienia zdania")
    return out


def _data_wejscia(mapa: dict[str, str], nr: str, krok: int = 0) -> _dt.date | None:
    """Data, od której obowiązuje brzmienie opisane odnośnikiem nr.

    Odnośnik bywa odesłaniem („Przez art. 26 pkt 3 ustawy, o której mowa w
    odnośniku 3."), a data stoi dopiero w tym docelowym — dlatego idziemy po
    łańcuchu. Odnośnik mówiący „obowiązuje DO wejścia w życie zmiany" opisuje
    koniec, nie początek, więc nie daje daty.

    Gdy odnośnik podaje dwie daty, pierwsza dotyczy ustawy zmieniającej, a
    druga — po średniku — samego przepisu („…ustawy (Dz. U. poz. 507), która
    wejdzie w życie z dniem 14 października 2026 r.; wejdzie w życie z dniem
    1 listopada 2028 r.”, art. 860 § 3 k.c.). Dla jednostki z tym odnośnikiem
    rozstrzyga druga; dla odnośnika, który tylko odsyła do tej ustawy („o
    której mowa w odnośniku 13”) — pierwsza.
    """
    tresc = mapa.get(nr)
    if tresc is None or krok > 3:
        return None
    if _DO_WEJSCIA_RE.search(tresc):
        return None
    daty = list(_W_ZYCIE_RE.finditer(tresc))
    m = (daty[0] if krok else daty[-1]) if daty else None
    if m:
        mies = _MIESIACE.get(m.group(2).lower())
        if mies:
            try:
                return _dt.date(int(m.group(3)), mies, int(m.group(1)))
            except ValueError:
                return None
    dalej = _ODESLANIE_RE.search(tresc)
    return _data_wejscia(mapa, dalej.group(1), krok + 1) if dalej else None


# Odnośnik jednostki, której przed datą wejścia w życie po prostu nie ma:
# „Dodany przez art. 1 pkt 4 lit. b ustawy…”, „Wejdzie w życie z dniem…”.
_DODANA_RE = re.compile(r'^\s*(?:dodan[yae]\b|wejdzie\s+w\s+życie|wchodzi\s+w\s+życie)',
                        re.IGNORECASE)


def _jeszcze_nie(mapa: dict[str, str], nr: str | None,
                 dzis: _dt.date) -> tuple[_dt.date, bool] | None:
    """Czy jednostka wydrukowana RAZ, z odnośnikiem nr przy swoim oznaczeniu,
    jeszcze nie obowiązuje. Zwraca (data wejścia w życie, czy to jednostka
    dodana) albo None, gdy odnośnik nie podaje przyszłej daty.

    Tekst jednolity drukuje jednostki dodane nowelizacją, która jeszcze nie
    weszła w życie (art. 94 pkt 2c k.p. w t.j. 2026: od 5.11.2026). Jednostki
    dodanej przed tą datą nie ma, więc się ją pomija. Inny odnośnik z przyszłą
    datą przy jedynym brzmieniu („W brzmieniu ustalonym przez…”) oznacza, że
    tekst nie drukuje brzmienia obowiązującego dziś — tego nie da się
    rozstrzygnąć, stąd druga wartość False (odmowa)."""
    if not nr:
        return None
    data = _data_wejscia(mapa, nr)
    if data is None or data <= dzis:
        return None
    return data, bool(_DODANA_RE.match(mapa.get(nr) or ""))


def _kanon_art(raw_art: str) -> str | None:
    """Numer artykułu w zapisie, jakim posługuje się źródło w data-id:
    385¹/385[1]/385(1) → '385_1', 36a → '36a', 59aa → '59aa', 45 → '45'."""
    s = re.sub(r'\s+', '', _indeks_na_nawias(raw_art.strip()))  # 131¹ᵃ → 131[1a]
    s = re.sub(r'([¹²³⁴⁵⁶⁷⁸⁹⁰]+)', lambda m: '_' + m.group(1).translate(_SUP), s)
    s = re.sub(r'[\[\(\^]\s*(\d+[a-z]*)\s*[\]\)]?', r'_\1', s).lower()
    return s if re.fullmatch(r'\d+[a-ząćęłńóśźż]*(?:_\d+[a-ząćęłńóśźż]*)*', s) else None


_SUB_RE = re.compile(r'<div class="unit unit_(?:para|pint|lett|tire|ustp)[^"]*" id="[^"]*" data-id="([^"]+)"')
_JEDN_RE = re.compile(r'<div class="unit unit_')
# (klucz aktu, numer artykułu, które wystąpienie) → (data wejścia w życie, czy
# artykuł dodany): brzmienie wydrukowane w tekście jednolitym z wyprzedzeniem
_przyszle_jedn: dict[tuple, tuple] = {}
# (klucz aktu, numer artykułu, które wystąpienie) → uwagi o wyborze brzmienia
# podjednostek; wartość NIEJEDNOZNACZNE = nie da się ustalić, które obowiązuje
_uwagi_jedn: dict[tuple, list[str]] = {}
NIEJEDNOZNACZNE = "NIEJEDNOZNACZNE"


def _uwaga_pominieta(opis: str, data: _dt.date) -> str:
    return (f"⚠ Pominięto {opis}: tekst jednolity drukuje tę jednostkę z wyprzedzeniem — "
            f"wejdzie w życie {data:%d.%m.%Y} i do tego dnia nie obowiązuje.")


def _opis_jednostki(data_id: str) -> str:
    """para_1_1 → „§ 1¹ / ust. 1¹”, pint_4 → „pkt 4”, lett_a → „lit. a”."""
    typ, _, nr = data_id.partition("_")
    nr = nr.replace("_", "")
    return {"para": f"§/ust. {nr}", "pint": f"pkt {nr}", "lett": f"lit. {nr}",
            "tire": "tiret", "ustp": f"ust. {nr}"}.get(typ, data_id)


def _dzieci(html: str, start: int, end: int) -> list[tuple[str, int, int]]:
    """Podjednostki leżące bezpośrednio w html[start:end] (bez zagnieżdżonych)."""
    out, koniec = [], start
    for m in _SUB_RE.finditer(html, start, end):
        if m.start() < koniec:
            continue
        k = min(_koniec_div(html, m.start()), end)
        out.append((m.group(1), m.start(), k))
        koniec = k
    return out


def _wlasny_odnosnik_html(html: str, start: int, end: int) -> str | None:
    """Numer odnośnika stojącego przy samym oznaczeniu jednostki otwartej na
    pozycji start („§ 1¹⁵⁾”, „2c)²⁷⁾”, „Art. 479⁴⁵. (uchylony)⁶⁸⁾”) — a nie
    pierwszego odnośnika gdziekolwiek w jej treści ani w jej podjednostkach."""
    otw = html.find(">", start) + 1
    nast = _JEDN_RE.search(html, otw, end)
    odn = _PIERWSZY_ODNOSNIK_RE.search(html, otw, nast.start() if nast else end)
    if not odn:
        return None
    przed = re.sub(r'\s+', ' ', _html.unescape(re.sub(r'<[^>]+>', ' ', html[otw:odn.start()])))
    przed = re.sub(r'\(\s*\w+(?:\s+\w+)?\s*\)\s*$', '', przed.strip())
    return odn.group(1) if len(przed.strip()) <= 14 else None


def _wybierz_podjednostki_html(html: str, mapa: dict[str, str], dzis: _dt.date,
                               uwagi: list[str]) -> str:
    """Usuwa z fragmentu artykułu nieobowiązujące brzmienia podjednostek.

    Tekst jednolity drukuje czasem DWA brzmienia tego samego paragrafu, ustępu
    lub punktu: dotychczasowe („obowiązuje do wejścia w życie zmiany…”) i nowe
    („wejdzie w życie z dniem…”). Art. 131¹ᵃ § 1 k.p.c. w t.j. 2026: brzmienie
    do 31.05.2026 i od 1.06.2026. Rozstrzyga data z odnośnika, jak na poziomie
    artykułu. Gdy daty nie da się odczytać — uwaga NIEJEDNOZNACZNE (odmowa).

    Usuwa też podjednostkę wydrukowaną raz, ale dodaną nowelizacją, która
    jeszcze nie weszła w życie (odnośnik „Dodany przez…” z przyszłą datą).
    """
    wytnij: list[tuple[int, int]] = []

    def rekur(a: int, b: int) -> None:
        dzieci = _dzieci(html, a, b)
        # brzmienia tej samej jednostki stoją bezpośrednio po sobie; ten sam
        # numer dalej (pkt 1 w ust. 1 i pkt 1 w ust. 3, gdy źródło nie zagnieżdża
        # punktów w ustępach) to inna jednostka
        grupy: list[tuple[str, list[int]]] = []
        for i, (did, _, _) in enumerate(dzieci):
            if grupy and grupy[-1][0] == did:
                grupy[-1][1].append(i)
            else:
                grupy.append((did, [i]))
        for did, idx in grupy:
            if len(idx) < 2:
                _, x, y = dzieci[idx[0]]
                stan = _jeszcze_nie(mapa, _wlasny_odnosnik_html(html, x, y), dzis)
                if stan and stan[1]:
                    wytnij.append((x, y))
                    uwagi.append(_uwaga_pominieta(_opis_jednostki(did), stan[0]))
                elif stan:
                    uwagi.append(NIEJEDNOZNACZNE)
                    uwagi.append(f"{_opis_jednostki(did)}: jedyne wydrukowane brzmienie "
                                 f"obowiązuje dopiero od {stan[0]:%d.%m.%Y}")
                continue
            daty = []
            for i in idx:
                _, x, y = dzieci[i]
                odn = _PIERWSZY_ODNOSNIK_RE.search(html, x, y)
                daty.append(_data_wejscia(mapa, odn.group(1)) if odn else None)
            wybor, nieznane = _wybierz_brzmienie(daty, dzis)
            if nieznane:
                uwagi.append(NIEJEDNOZNACZNE)
                uwagi.append(f"{_opis_jednostki(did)}: {len(idx)} brzmienia bez czytelnej daty")
                continue
            for j, i in enumerate(idx):
                if j != wybor:
                    wytnij.append(dzieci[i][1:])
            d = daty[wybor]
            uwagi.append(f"⚠ Tekst jednolity drukuje {len(idx)} brzmienia {_opis_jednostki(did)}. "
                         + (f"Powyżej brzmienie obowiązujące od {d:%d.%m.%Y}." if d else
                            "Powyżej brzmienie obowiązujące w dniu tego tekstu jednolitego.")
                         + "".join(f" Kolejne wchodzi w życie {x:%d.%m.%Y}." for x in daty
                                   if x and x > dzis))
        for did, x, y in dzieci:
            if (x, y) not in wytnij:
                rekur(html.index(">", x) + 1, y)

    rekur(0, len(html))
    for x, y in sorted(wytnij, reverse=True):
        html = html[:x] + html[y:]
    return html


# Pogrubiony nagłówek artykułu w treści akapitu: t.j. u.ś.u.d.e. (Dz.U. 2024 poz. 1513)
# drukuje „<B>Art. 15. </B>” w akapicie art. 14 ust. 4 i nie daje art. 15 własnej jednostki.
_WKLEJONY_ART_RE = re.compile(r'<B\b[^>]*>\s*Art\.(?:\s|&nbsp;)*(\d+[a-z]*)\s*\.\s*</B>', re.IGNORECASE)


def _jednostki_html(key: str, raw_html: str) -> list[tuple[str, str, _dt.date | None]]:
    """Artykuły właściwego aktu wg znaczników źródła, w kolejności dokumentu.

    Pomija przepisy przejściowe ustaw nowelizujących — źródło oznacza je
    prefiksem `pass_` w atrybucie id, więc nie trzeba ich zgadywać z numeracji.
    W treści artykułu zostaje tylko obowiązujące brzmienie każdej podjednostki
    (uwagi o wyborze w _uwagi_jedn).
    """
    if key in _jedn_cache:
        return _jedn_cache[key]
    mapa = _odnosniki(key, raw_html)
    dzis = _dzis()
    out = []
    jedn_re = _UNIT_RE if 'class="unit unit_arti' in raw_html else _UNIT_PARA_RE
    for m in jedn_re.finditer(raw_html):
        if 'pass_' in m.group(1):
            continue
        fragment = raw_html[m.start():_koniec_div(raw_html, m.start())]
        odn = _PIERWSZY_ODNOSNIK_RE.search(fragment)
        przyszle = _jeszcze_nie(mapa, _wlasny_odnosnik_html(fragment, 0, len(fragment)), dzis)
        uwagi: list[str] = []
        fragment = _wybierz_podjednostki_html(fragment, mapa, dzis, uwagi)
        fragment, _ = _wybierz_zdania_html(fragment, mapa, dzis, uwagi)
        # tylko odnośniki, które ZOSTAŁY we fragmencie: rozstrzygnięte wystąpienie znika
        # razem z nowym brzmieniem, nierozstrzygnięte (inne wystąpienie tego samego
        # odnośnika) nadal daje odmowę
        zdania = _zdania_dwa_brzmienia(mapa, _PIERWSZY_ODNOSNIK_RE.findall(fragment))
        if zdania:
            uwagi += [NIEJEDNOZNACZNE] + zdania
        # „arti_131_1_a” (t.j. 2024) i „arti_131_1a” to ten sam art. 131¹ᵃ — klucz jak
        # w _kanon_art; inaczej artykuł z literą w indeksie szedł ścieżką zapasową,
        # która nie sprawdza dat wejścia w życie (#11)
        num = re.sub(r'_(\d+)_([a-z]+)$', r'_\1\2', m.group(2).lower())
        ktore = sum(1 for n, *_ in out if n == num)
        if uwagi:
            _uwagi_jedn[(key, num, ktore)] = uwagi
        if przyszle:
            _przyszle_jedn[(key, num, ktore)] = przyszle
        # nagłówek innego artykułu wklejony w treść tej jednostki (za jej własnym <h3>),
        # gdy źródło nie ma dla niego osobnej jednostki — tniemy przed nim (#7)
        wklejony = _WKLEJONY_ART_RE.search(fragment, max(fragment.find("</h3>") + 5, 5))
        if wklejony and (wklejony.group(1).lower() == num.split("_")[0]
                         or f'data-id="arti_{wklejony.group(1).lower()}"' in raw_html):
            wklejony = None
        tekst = fragment[:wklejony.start()] if wklejony else fragment
        out.append((num, _strip_html(tekst),
                    _data_wejscia(mapa, odn.group(1)) if odn else None))
        if wklejony:
            out.append((wklejony.group(1).lower(), _strip_html(fragment[wklejony.start():]), None))
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
    # akty numerujące artykuły cyframi rzymskimi („Art. I.” — przepisy wprowadzające
    # k.p., DU/1974/142): nie ma tu czego naprawiać, a int() by się wywrócił
    if any(not re.match(r'\d', n) for n, *_ in jedn):
        return jedn
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


class Niejednoznaczne(Exception):
    """Tekst jednolity drukuje kilka brzmień jednostki, a z odnośników nie da
    się ustalić, które obowiązuje — narzędzie odmawia zamiast zgadywać."""


class JeszczeNieObowiazuje(Exception):
    """Tekst jednolity drukuje artykuł z wyprzedzeniem: jego jedyne (albo
    pierwsze) brzmienie wejdzie w życie dopiero w podanym dniu."""

    def __init__(self, data: _dt.date, dodany: bool):
        super().__init__(f"{data:%d.%m.%Y}")
        self.data, self.dodany = data, dodany


def _odmowa_przyszly(info: dict, ref: str, adres: str, url_pdf: str,
                     data: _dt.date, dodany: bool) -> str:
    if dodany:
        return (f"❌ {ref} {info['name']}: przepis jeszcze nie obowiązuje. Tekst jednolity "
                f"({adres}) drukuje go z wyprzedzeniem — dodaje go nowelizacja, która wejdzie "
                f"w życie {data:%d.%m.%Y}. Do tego dnia tego artykułu nie ma w obowiązującym "
                f"stanie prawnym, więc jego brzmienia nie podaję.\n"
                f"Przyszłe brzmienie w Dz.U.: {url_pdf}")
    return (f"❌ {ref} {info['name']}: tekst jednolity ({adres}) drukuje tylko brzmienie, które "
            f"wejdzie w życie {data:%d.%m.%Y}, a brzmienia obowiązującego dziś w nim nie ma — "
            f"nie podaję przyszłego brzmienia jako obowiązującego.\nSprawdź w Dz.U.: {url_pdf}")


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

    dzis = _dzis()
    wybor, nieznane = 0, False
    if len(trafienia) > 1:
        for i, (_, data) in enumerate(trafienia[1:], start=1):
            if data is None:
                nieznane = True
            elif data <= dzis:
                wybor = i
    tekst, data_wyboru = trafienia[wybor]
    przyszle = _przyszle_jedn.get((key, klucz, wybor))
    if przyszle:
        raise JeszczeNieObowiazuje(*przyszle)
    uwagi_pod = _uwagi_jedn.get((key, klucz, wybor), [])
    if NIEJEDNOZNACZNE in uwagi_pod:
        raise Niejednoznaczne("; ".join(u for u in uwagi_pod if u != NIEJEDNOZNACZNE))
    if not _wiarygodny(tekst):
        return None
    if ustep:
        tekst = _cut_ustep(tekst, ustep)
        if not tekst:
            return None

    for u in uwagi_pod:
        tekst += "\n\n" + u
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
    # „§ N” jako jednostka główna tylko w tekście bez nagłówków „Art.” — inaczej
    # „art. 1” aktu numerowanego rzymsko (DU/1974/142: „Art. I.”) trafiał w „§ 1.”
    # cudzego artykułu
    wzorce = [(rf'Art\.\s*{frag}\s*\.', r'\bArt\.\s*\d+')]
    if not re.search(r'\bArt\.\s*(?:\d|[IVXLC]+\s*\.)', text):
        wzorce.append((rf'§\s*{frag}\s*\.', r'§\s*\d+'))
    for prefix, granica in wzorce:
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


# Granice artykułu w akcie UE poza następnym „Artykuł N": nagłówki struktury
# (ROZDZIAŁ/SEKCJA/TYTUŁ/ZAŁĄCZNIK — wielkie litery, żeby „tytuł prawny" w treści
# nie ucinał) i formuła końcowa aktu przed podpisami i przypisami.
_EU_BREAK = r'\b(?:ROZDZIAŁ|SEKCJA|TYTUŁ|ZAŁĄCZNIK|PROTOKÓŁ|PROTOKOŁY|DEKLARACJE)\b|\bSporządzono w\b'
# nagłówek artykułu aktu UE: „Artykuł 101”, nie odesłanie „(dawny artykuł 81 TWE)”
# ani „artykuł 5” w tekście — wielka litera, bez „dawny ” i nawiasu przed
_NAGLOWEK_ART_EU = r'(?<!dawny )(?<!\()\bArtykuł\s+'


def extract_eu_article(text: str, art: str, ustep: str | None) -> str | None:
    m = re.search(rf'{_NAGLOWEK_ART_EU}{re.escape(art)}(?![\w])', text)
    if not m:
        return None
    rest = text[m.end():]
    ends = [x.start() for x in (
        re.search(rf'{_NAGLOWEK_ART_EU}\d+[a-z]?(?![\w])', rest),
        re.search(_EU_BREAK, rest),
    ) if x]
    end = m.end() + min(ends) if ends else min(m.start() + 5000, len(text))
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
    ident, data, zmieniajace = zr
    if not data:
        return f"\n(tekst jednolity {ident})"
    aktualnosc, _, _ = _aktualnosc_pl(zmieniajace, data)
    return f"\n(tekst jednolity {ident} z {data})\nAktualność: {aktualnosc}"


def _dla_modelu_html(info: dict) -> str:
    """Linia [dla modelu] dla ścieżki, w której najnowszy t.j. jest w HTML."""
    zr = _zrodlo.get(_klucz_pl(info))
    if not zr or len(zr) != 3 or not zr[1]:
        return ""
    ident, data, zmieniajace = zr
    _, kod, pola = _aktualnosc_pl(zmieniajace, data)
    return (f"\n\n[dla modelu] zrodlo=urzedowy_html; aktualnosc={kod}{pola}; "
            f"cytuj_jako=„tekst urzędowy, t.j. {ident}”; nie_nazywaj_tekstem_urzedowym=nie_dotyczy")


def _odmiana_nowelizacji(n: int) -> str:
    if n == 1:
        return "1 nowelizacja"
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return f"{n} nowelizacje"
    return f"{n} nowelizacji"


def _nowelizacje_miedzy(zmieniajace: list[dict], od: str, do: str) -> int:
    return sum(1 for e in zmieniajace
               if od and do and od < (e.get("date") or "") <= do)


def _wybierz_brzmienie(trafienia: list, dzis: _dt.date) -> tuple[int, bool]:
    """Indeks brzmienia obowiązującego dziś spośród kilku wydrukowanych (po dacie
    z odnośnika; przy nieznanej dacie zostaje pierwsze) i flaga, czy jakaś data
    była nieczytelna."""
    wybor, nieznane = 0, False
    for i, data in enumerate(trafienia[1:], start=1):
        if data is None:
            nieznane = True
        elif data <= dzis:
            wybor = i
    return wybor, nieznane


async def _odpowiedz_tekst_u(info: dict, art: str, ustep: str | None, ref: str) -> str:
    """Akt bez tekstu jednolitego w Dz.U., z tekstem ujednoliconym Kancelarii Sejmu
    w ELI (Konstytucja). Tekst nieurzędowy: kontrola warstwy tekstowej PDF i sprawdzenie,
    że podstawa opracowania (nagłówek PDF) wymienia każdy akt zmieniający z ELI."""
    from legal_cite import pdf_tj
    ident = f"{info['pub']}/{info['year']}/{info['pos']}"
    url_pdf = f"https://api.sejm.gov.pl/eli/acts/{ident}/text/U/{info['tekst_u']}"
    if not pdf_tj.konwerter_dostepny():
        return f"❌ {ref} {info['name']}: konwerter eli2md nie jest zainstalowany po stronie serwera"
    async with httpx.AsyncClient(follow_redirects=True, timeout=30, headers=_HEADERS) as c:
        meta = (await c.get(f"https://api.sejm.gov.pl/eli/acts/{ident}")).json()
    try:
        od = await pdf_tj.odczyt(ident, meta, plik_u=info["tekst_u"])
    except Exception as e:  # sieć, uszkodzony PDF, błąd konwertera
        logger.warning("odczyt tekstu U %s blad=%s", ident, type(e).__name__)
        return (f"❌ {ref} {info['name']}: nie udało się pobrać lub skonwertować tekstu "
                f"ujednoliconego ({type(e).__name__}). Sprawdź: {url_pdf}")
    klucz = _kanon_art(art)
    trafienia = od.znajdz(klucz) if klucz else []
    if not trafienia:
        return f"❌ {ref} nie znaleziony w {info['name']}. Sprawdź numer artykułu."
    jedn = trafienia[0]
    w = pdf_tj.wiernosc_pdftotext(jedn, od.raw_tok, od.wyjasnienia) if od.raw_tok else None
    if w is None or not w.ok:
        return (f"❌ {ref} {info['name']}: odczyt tekstu ujednoliconego nie przeszedł kontroli "
                f"warstwy tekstowej PDF ({w.powod if w else 'brak pdftotext'}). Sprawdź: {url_pdf}")
    tekst = jedn.czysty()
    if ustep:
        tekst = _cut_ustep(tekst, ustep)
        if not tekst:
            return f"❌ {ref} nie znaleziony w {info['name']}. Sprawdź numer ustępu."
    zmieniajace = sorted(((e.get("id") or "?", e.get("date") or "")
                          for e in (meta.get("references") or {}).get("Akty zmieniające", [])),
                         key=lambda x: (x[1], x[0]))
    podstawa = od.raw_tok[:400]  # nagłówek „Opracowano na podstawie: Dz. U. … poz. …”
    brak = [i for i, _ in zmieniajace if i.split("/")[-1] not in podstawa]
    lista = ", ".join(f"{_adres_dz_u(i)} ({_data_pl(d)})" for i, d in zmieniajace) or "brak"
    if brak:
        aktualnosc = (f"nieustalona — podstawa opracowania tekstu ujednoliconego nie wymienia: "
                      f"{', '.join(_adres_dz_u(i) for i in brak)}")
        kod = "nieustalona_akt_zmieniajacy_poza_tekstem_ujednoliconym"
    else:
        aktualnosc = (f"wg wykazu API ELI akty zmieniające ({lista}) są uwzględnione w podstawie "
                      f"opracowania tekstu ujednoliconego")
        kod = "potwierdzona_wg_wykazu_eli"
    return (f"📄 **{info['name']}**, {ref}\n"
            f"(źródło: api.sejm.gov.pl, tekst ujednolicony Kancelarii Sejmu — NIEURZĘDOWY; "
            f"wiążący jest tekst w Dz.U. 1997 nr 78 poz. 483 i aktach zmieniających; "
            f"odczyt {od.konwerter}, kontrola pdftotext: zaliczona; PDF: {url_pdf})\n"
            f"Aktualność: {aktualnosc}\n\n{tekst}\n\n"
            f"[dla modelu] zrodlo=tekst_ujednolicony_kancelarii_sejmu; aktualnosc={kod}; "
            f"cytuj_jako=„{info['name']}, tekst ujednolicony Kancelarii Sejmu (nieurzędowy)”; "
            f"nie_nazywaj_tekstem_urzedowym=tak")


async def _odpowiedz_pl(info: dict, art: str, ustep: str | None, ref: str) -> str:
    """Brzmienie przepisu PL. Najpierw WERSJA, potem format: podstawą jest
    najnowszy tekst jednolity. Gdy API daje go w HTML — ścieżka urzędowego
    HTML. Gdy tylko w PDF — nieurzędowy odczyt PDF z kontrolami (pdf_tj).
    Starszy HTML sam w sobie nie jest odpowiedzią na pytanie o aktualne
    brzmienie, więc przy odmowie nie jest podawany."""
    if info.get("tekst_u"):
        return await _odpowiedz_tekst_u(info, art, ustep, ref)
    tj = await _teksty_jednolite(info)
    if not tj:
        return f"❌ Nie udało się pobrać metadanych {info['name']} z api.sejm.gov.pl"
    najnowszy = tj[0]
    if najnowszy.get("html_awaria") and najnowszy["meta"].get("textPDF"):
        # Awaria HTML ELI (wszystkie text.html → 500, np. 26.10.2026), a ten sam t.j.
        # jest w PDF: odczyt PDF z kontrolą warstwy tekstowej, z jawną adnotacją,
        # zamiast odmowy dla całego aktu.
        return await _odpowiedz_pdf(info, tj, art, ustep, ref)
    if najnowszy.get("html_awaria"):
        return (f"❌ {ref} {info['name']}: API ELI Sejmu nie oddaje teraz tekstu HTML "
                f"najnowszego tekstu jednolitego ({najnowszy['id']}) — awaria po stronie "
                f"api.sejm.gov.pl. Spróbuj za chwilę.")
    if najnowszy["html"]:
        text = await _fetch_pl(info)
        if text is None:
            return f"❌ Nie udało się pobrać {info['name']} (sieć/ELI)"
        key = _klucz_pl(info)
        raw = _html_cache.get(key)
        try:
            result = extract_pl_article_html(key, raw, art, ustep) if raw else None
        except Niejednoznaczne as e:
            return (f"❌ {ref} {info['name']}: tekst jednolity drukuje kilka brzmień tej "
                    f"jednostki i z odnośników nie da się ustalić, które obowiązuje ({e}). "
                    f"Sprawdź w Dz.U.: https://api.sejm.gov.pl/eli/acts/{najnowszy['id']}/text.pdf")
        except JeszczeNieObowiazuje as e:
            return _odmowa_przyszly(
                info, ref, najnowszy["meta"].get("displayAddress") or najnowszy["id"],
                f"https://api.sejm.gov.pl/eli/acts/{najnowszy['id']}/text.pdf", e.data, e.dodany)
        jedn_html = _jednostki_html(key, raw) if raw else []
        if result is None and jedn_html and not any(re.match(r'\d', n) for n, *_ in jedn_html):
            return (f"❌ {ref} {info['name']}: akt numeruje artykuły cyframi rzymskimi "
                    f"(„Art. I.”, „Art. II.”) — takie numery nie są jeszcze obsługiwane.")
        if result is None and not (raw and _kanon_art(art) and any(
                n == _kanon_art(art) for n, *_ in _jednostki_html(key, raw))):
            # ścieżka zapasowa (regex po tekście) tylko, gdy struktura źródła nie zna
            # artykułu; inaczej oddałaby wszystkie wydrukowane brzmienia naraz
            result = extract_pl_article(text, art, ustep)
        if not result:
            return f"❌ {ref} nie znaleziony w {info['name']}. Sprawdź numer artykułu."
        podstawa = _podstawa_tekstu(info)
        return (f"📜 **{info['name']}**, {ref}\n(źródło: api.sejm.gov.pl, tekst urzędowy HTML)"
                f"{podstawa}\n\n{result}{_dla_modelu_html(info)}")
    return await _odpowiedz_pdf(info, tj, art, ustep, ref)


def _odmowa_pdf(info: dict, ref: str, ident: str, adres: str, url_pdf: str, powod: str,
                starszy: str | None) -> str:
    tekst = (f"❌ {ref} {info['name']}: najnowszy tekst jednolity ({adres}, {ident}) jest "
             f"dostępny w API ELI tylko jako PDF, a nieurzędowy odczyt tego artykułu nie "
             f"przeszedł kontroli: {powod}.")
    if starszy:
        tekst += (f" Starszego brzmienia z t.j. {starszy} (HTML) nie podaję, bo mogło "
                  f"zostać zmienione.")
    return tekst + f"\nSprawdź w urzędowym PDF: {url_pdf}"


async def _odpowiedz_pdf(info: dict, tj: list[dict], art: str, ustep: str | None,
                         ref: str) -> str:
    from legal_cite import pdf_tj

    najnowszy = tj[0]
    ident = najnowszy["id"]
    pub, year, pos = ident.split("/")
    url_pdf = f"https://api.sejm.gov.pl/eli/acts/{ident}/text.pdf"
    adres = najnowszy["meta"].get("displayAddress") or ident
    starszy = next((w for w in tj if w["html"]), None)
    starszy_id = starszy["id"] if starszy else None

    if not pdf_tj.konwerter_dostepny():
        return _odmowa_pdf(info, ref, ident, adres, url_pdf,
                           "konwerter eli2md nie jest zainstalowany po stronie serwera",
                           starszy_id)
    try:
        od = await pdf_tj.odczyt(ident, najnowszy["meta"])
    except Exception as e:  # sieć, uszkodzony PDF, błąd konwertera
        logger.warning("odczyt pdf %s blad=%s", ident, type(e).__name__)
        return _odmowa_pdf(info, ref, ident, adres, url_pdf,
                           f"nie udało się pobrać lub skonwertować PDF ({type(e).__name__})",
                           starszy_id)

    klucz = _kanon_art(art)
    if not klucz:
        return f"❌ Nierozpoznany numer artykułu: '{art}'"
    trafienia = od.znajdz(klucz)

    # starszy tekst jednolity w HTML — niezależne źródło do porównania
    html_teksty: list[str] = []
    slownik: set[str] = set()
    data_html = ""
    if starszy:
        await _fetch_pl(info)
        key = _klucz_pl(info)
        if key in _html_cache:
            jedn = _jednostki_html(key, _html_cache[key])
            html_teksty = [t for n, t, _ in jedn if n == klucz]
            slownik = pdf_tj.slownik_html(t for _, t, _ in jedn)
        data_html = starszy["meta"].get("announcementDate") or ""

    if not trafienia:
        if html_teksty:
            return _odmowa_pdf(info, ref, ident, adres, url_pdf,
                               "artykuł jest w starszym tekście jednolitym, a w odczycie "
                               "najnowszego go nie ma", starszy_id)
        return f"❌ {ref} nie znaleziony w {info['name']} ({adres}). Sprawdź numer artykułu."
    if not od.monotoniczne:
        return _odmowa_pdf(info, ref, ident, adres, url_pdf,
                           "numery artykułów w odczycie nie rosną w kolejności dokumentu, "
                           "więc granicom artykułów nie można ufać", starszy_id)

    dzis = _dzis()
    wybor, nieznane = _wybierz_brzmienie([j.data for j in trafienia], dzis)
    jedn = trafienia[wybor]
    # artykuł wydrukowany z wyprzedzeniem (dodany nowelizacją, która jeszcze nie
    # weszła w życie) nie jest obowiązującym brzmieniem
    przyszle = _jeszcze_nie(od.przypisy, jedn.wlasny_odnosnik, dzis)
    if przyszle:
        return _odmowa_przyszly(info, ref, adres, url_pdf, *przyszle)
    if jedn.niejednoznaczne:
        return _odmowa_pdf(info, ref, ident, adres, url_pdf,
                           "tekst jednolity drukuje kilka brzmień jednostki i z odnośników nie da "
                           "się ustalić, które obowiązuje (" + "; ".join(jedn.uwagi) + ")",
                           starszy_id)

    # kontrola 1: starszy urzędowy HTML
    rel = pdf_tj.porownaj_z_html(jedn, html_teksty)
    awaria_html = False
    zmieniajace = najnowszy.get("zmieniajace") or []
    # kontrola 2: warstwa tekstowa PDF drugim czytnikiem
    if od.raw_tok:
        w = pdf_tj.wiernosc_pdftotext(jedn, od.raw_tok, od.wyjasnienia)
        kontrola_pdf = "zaliczona" if w.ok else f"niezaliczona ({w.powod})"
    else:
        w = None
        kontrola_pdf = "niewykonana (brak pdftotext na serwerze)"

    if rel == "identyczny":
        # Dwa niezależne źródła dają te same słowa: podajemy tekst urzędowy
        # (HTML), a najnowszy t.j. potwierdza, że artykuł się nie zmienił.
        tekst = next(h for h in html_teksty
                     if "".join(pdf_tj.tokeny(h)) == "".join(pdf_tj.tokeny(jedn.tekst)))
        zrodlo = "urzedowy_html"
        wiernosc = "potwierdzona_identycznym_brzmieniem_w_najnowszym_tj"
        naglowek = (f"(źródło: api.sejm.gov.pl, tekst urzędowy HTML t.j. {starszy_id}; "
                    f"brzmienie identyczne w najnowszym t.j. {adres} z {od.data_tj}, "
                    f"dostępnym tylko w PDF — odczyt {od.konwerter}, kontrola pdftotext: "
                    f"{kontrola_pdf})")
    else:
        if w is None or not w.ok:
            return _odmowa_pdf(info, ref, ident, adres, url_pdf,
                               f"kontrola warstwy tekstowej PDF {kontrola_pdf}", starszy_id)
        if rel == "rozny":
            miedzy = _nowelizacje_miedzy(zmieniajace, data_html, od.data_tj)
            if jedn.odnosniki:
                wyjasnienie = ("odnośnik przy jednostce: "
                               + (od.przypisy.get(jedn.odnosniki[0]) or "")[:160])
            elif miedzy:
                wyjasnienie = (f"między t.j. {starszy_id} ({data_html}) a tym t.j. weszło "
                               f"w życie {_odmiana_nowelizacji(miedzy)}")
            else:
                return _odmowa_pdf(info, ref, ident, adres, url_pdf,
                                   f"brzmienie różni się od t.j. {starszy_id} (HTML), a ani "
                                   "odnośnik, ani wykaz nowelizacji tej różnicy nie tłumaczą",
                                   starszy_id)
            opis_html = f"różne od t.j. {starszy_id} (HTML); {wyjasnienie}"
        else:
            awaria_html = any(w.get("html_awaria") for w in tj) and not starszy_id
            # Tryb awaryjny (decyzja 27.10.2026): przy awarii HTML ELI porównania ze
            # starszym t.j. nie da się wykonać, ale kontrola warstwy tekstowej PDF
            # (zaliczona — inaczej odmowa wyżej) zostaje; wynik jawnie oznaczony.
            opis_html = ("NIEWYKONANE — API ELI nie oddaje teraz HTML (awaria "
                         "api.sejm.gov.pl); odczyt potwierdzony tylko warstwą tekstową PDF"
                         if awaria_html else
                         f"artykułu nie ma w t.j. {starszy_id} (HTML) — dodany później"
                         if starszy_id else "brak starszego t.j. w HTML do porównania")
        tekst, ile = pdf_tj.napraw_sklejki(jedn.czysty(), slownik)
        zrodlo = "nieurzedowy_odczyt_pdf"
        wiernosc = ("zaliczona_pdftotext_bez_porownania_html_awaria_eli"
                    if awaria_html else "zaliczona_pdftotext")
        naglowek = (f"(źródło: api.sejm.gov.pl, t.j. {adres} z {od.data_tj} — tylko PDF)\n"
                    f"⚠ NIEURZĘDOWY ODCZYT z urzędowego PDF: {od.konwerter}; "
                    f"PDF sha256 {od.sha256[:16]}…; wiążący jest PDF: {url_pdf}\n"
                    f"Kontrola odczytu: warstwa tekstowa PDF ({od.pdftotext}) — {kontrola_pdf}; "
                    f"względem starszego t.j.: {opis_html}"
                    + (f"; rozdzielono {ile} wyrazów sklejonych w warstwie PDF" if ile else "")
                    + ")")

    if ustep:
        tekst = _cut_ustep(tekst, ustep)
        if not tekst:
            return f"❌ {ref} nie znaleziony w {info['name']} ({adres}). Sprawdź numer ustępu."

    aktualnosc, akt_kod, pola_nowel = _aktualnosc_pl(zmieniajace, od.data_tj)

    uwagi = "".join("\n\n" + u for u in jedn.uwagi)
    if len(trafienia) > 1:
        uwagi += f"\n\n⚠ Tekst jednolity drukuje {len(trafienia)} brzmienia tego artykułu. "
        uwagi += (f"Powyżej brzmienie obowiązujące od {jedn.data:%d.%m.%Y}."
                  if jedn.data else
                  "Powyżej brzmienie obowiązujące w dniu tego tekstu jednolitego.")
        przyszle = [j.data for j in trafienia if j.data and j.data > dzis]
        if przyszle:
            uwagi += (" Kolejne wchodzi w życie "
                      + ", ".join(f"{d:%d.%m.%Y}" for d in sorted(przyszle)) + ".")
        if nieznane:
            uwagi += (" Przy co najmniej jednym brzmieniu nie udało się odczytać daty "
                      "wejścia w życie z odnośnika — sprawdź odnośniki w Dz.U.")

    znacznik = "📜" if zrodlo == "urzedowy_html" else "📄"
    cytuj = (f"tekst urzędowy, t.j. {starszy_id}, potwierdzony w {adres}"
             if zrodlo == "urzedowy_html" else
             f"nieurzędowy odczyt {adres} (PDF), nie tekst urzędowy")
    return (f"{znacznik} **{info['name']}**, {ref}\n{naglowek}\n"
            f"Aktualność: {aktualnosc}\n\n{tekst}{uwagi}\n\n"
            f"[dla modelu] zrodlo={zrodlo}; wiernosc={wiernosc}; aktualnosc={akt_kod}"
            f"{pola_nowel}; "
            f"cytuj_jako=„{cytuj}”; nie_nazywaj_tekstem_urzedowym="
            f"{'nie_dotyczy' if zrodlo == 'urzedowy_html' else 'tak'}")


# --- Dowolna ustawa po adresie Dz.U. (bez słownika) ---
# „Dz.U. 2024 poz. 1061”, „Dz. U. z 2024 r. poz. 1061”, „Dz.U. 2018 nr 12 poz. 34”, „DU/2024/1061”.
# Adres tekstu jednolitego (obwieszczenie) jest zamieniany na akt, którego dotyczy
# („Tekst jednolity dla aktu” w ELI) — silnik pracuje na akcie pierwotnym.
_ADRES_DZU_RE = re.compile(
    r'(?i)\b(?P<pub>Dz\.?\s*U|M\.?\s*P)\.?\s*(?:z\s*)?(?P<rok>\d{4})\s*(?:r\.)?\s*,?\s*(?:nr\s*\d+\s*,?\s*)?'
    r'poz\.?\s*(?P<poz>\d+)'
    r'|\b(?P<pub2>DU|MP)/(?P<rok2>\d{4})/(?P<poz2>\d+)\b')
# akty czytane po adresie; umowy międzynarodowe ELI drukuje dwujęzycznie w dwóch kolumnach
# (skan EKPCz po konwersji to przemieszane kolumny PL/EN) — odmowa zamiast niewiarygodnego odczytu
_TYPY_Z_ADRESU = ("Ustawa", "Rozporządzenie", "Uchwała", "Zarządzenie", "Regulamin")
_TYPY_UMOWY = ("Konwencja", "Umowa międzynarodowa", "Umowa", "Protokół", "Traktat", "Porozumienie", "Karta")
_akty_z_adresu: dict[str, tuple[float, dict | str]] = {}


async def _akt_z_adresu(tekst: str) -> dict | str | None:
    """Słownik aktu (jak w PL_ACTS) dla adresu Dz.U. w tekście, komunikat odmowy
    (str) albo None, gdy w tekście nie ma adresu."""
    m = _ADRES_DZU_RE.search(tekst or "")
    if not m:
        return None
    if m.group("rok"):
        pub = "DU" if m.group("pub").lower().startswith("d") else "MP"
        rok, poz = m.group("rok"), m.group("poz")
    else:
        pub, rok, poz = m.group("pub2").upper(), m.group("rok2"), m.group("poz2")
    ident = klucz = f"{pub}/{rok}/{poz}"
    if klucz in _akty_z_adresu and time.time() - _akty_z_adresu[klucz][0] < _KATALOG_TTL:
        return _akty_z_adresu[klucz][1]
    base = "https://api.sejm.gov.pl/eli/acts"
    async with httpx.AsyncClient(follow_redirects=True, timeout=25, headers=_HEADERS) as c:
        r = await c.get(f"{base}/{ident}")
        if r.status_code == 404:
            return (f"❌ W {'Dzienniku Ustaw' if pub == 'DU' else 'Monitorze Polskim'} nie ma pozycji "
                    f"{_adres_dz_u(ident)} (API ELI: 404).")
        r.raise_for_status()
        meta = r.json()
        dla = (meta.get("references") or {}).get("Tekst jednolity dla aktu") or []
        if dla and dla[0].get("id"):
            ident = dla[0]["id"]
            r = await c.get(f"{base}/{ident}")
            r.raise_for_status()
            meta = r.json()
    if meta.get("type") in _TYPY_UMOWY:
        wynik = (f"❌ {_adres_dz_u(ident)} to {(meta.get('type') or 'akt').lower()} "
                 f"({(meta.get('title') or '')[:100]}). Umowy międzynarodowe są w ELI tylko jako PDF "
                 f"drukowany dwujęzycznie w dwóch kolumnach — odczyt nie jest wiarygodny, więc narzędzie "
                 f"go nie podaje. Wiążący jest PDF: https://api.sejm.gov.pl/eli/acts/{ident}/text.pdf")
    elif meta.get("type") not in _TYPY_Z_ADRESU:
        wynik = (f"❌ {_adres_dz_u(ident)} to {(meta.get('type') or 'akt').lower()}. Po adresie "
                 f"Dz.U. albo M.P. narzędzie obsługuje ustawy, rozporządzenia, uchwały, zarządzenia "
                 f"i regulaminy.")
    elif (meta.get("entryIntoForce") or "") > _dt.date.today().isoformat() \
            or "oczekuj" in (meta.get("status") or ""):
        wynik = (f"❌ {_adres_dz_u(ident)} ({meta.get('title', '')[:120]}) jeszcze nie weszła "
                 f"w życie (wg ELI: {meta.get('entryIntoForce') or meta.get('status')}) — narzędzie "
                 f"podaje brzmienie obowiązujących ustaw.")
    elif meta.get("status") in ("uchylony", "wygaśnięcie aktu", "akt jednorazowy"):
        wynik = (f"❌ {_adres_dz_u(ident)} ({meta.get('title', '')[:120]}) ma w ELI status "
                 f"„{meta.get('status')}” — narzędzie podaje brzmienie obowiązujących ustaw.")
    else:
        pub, rok, poz = ident.split("/")
        tytul = re.sub(r'\s+', ' ', meta.get("title") or ident).strip().rstrip('.')
        wynik = dict(pub=pub, year=int(rok), pos=int(poz), name=tytul)
    _akty_z_adresu[klucz] = (time.time(), wynik)
    return wynik


# --- Ustawa po tytule (katalog z API ELI) ---
# „ustawy o ochronie konkurencji i konsumentów”, „Prawo bankowe”: katalog obowiązujących
# ustaw merytorycznych (bez nowelizujących, ratyfikacyjnych, budżetowych) pobierany
# z wyszukiwarki ELI raz na dobę. Dopasowanie dokładne po przedmiocie albo — dla form
# odmienionych („Prawa bankowego”) — po rdzeniach wyrazów, wyłącznie przy jednym
# trafieniu; inaczej odmowa z listą kandydatów. Nigdy nie zgadujemy aktu.
_katalog: tuple[float, list[dict]] | None = None
_KATALOG_TTL = 24 * 3600
_NIEMERYTORYCZNE = ("o zmianie", "o zmianach", "zmieniająca", "ratyfikacji", "ustawa budżetowa")


async def _katalog_ustaw() -> list[dict]:
    global _katalog
    if _katalog and time.time() - _katalog[0] < _KATALOG_TTL:
        return _katalog[1]
    out, off = [], 0
    async with httpx.AsyncClient(timeout=60, headers=_HEADERS) as c:
        while True:
            r = await c.get("https://api.sejm.gov.pl/eli/acts/search", params={
                "publisher": "DU", "type": "Ustawa", "inForce": "1", "limit": 500, "offset": off})
            r.raise_for_status()
            it = r.json().get("items", [])
            out += [x for x in it
                    if not any(n in (x.get("title") or "").lower() for n in _NIEMERYTORYCZNE)
                    and x.get("status") in ("akt posiada tekst jednolity", "obowiązujący")]
            if len(it) < 500:
                break
            off += 500
    _katalog = (time.time(), out)
    return out


def _przedmiot(tytul: str) -> str:
    """„Ustawa z dnia 16 lutego 2007 r. o ochronie konkurencji i konsumentów” →
    „o ochronie konkurencji i konsumentów”; „… r. - Prawo bankowe” → „prawo bankowe”;
    „ustawy o ochronie…” (z cytatu) → „o ochronie…”."""
    t = re.sub(r'\s+', ' ', tytul or '').strip().lower().rstrip('.')
    t = re.sub(r'^ustaw\w*\s*', '', t)
    t = re.sub(r'^z\s+dnia\s+\d{1,2}\s+\S+\s+\d{4}\s*r\.?\s*', '', t)
    return re.sub(r'^[-–]\s*', '', t).strip()


def _rdzenie(t: str) -> tuple[str, ...]:
    return tuple(w[:4] for w in re.findall(r'\w+', t) if len(w) >= 3)


def _wyrazy(t: str) -> list[str]:
    return [w for w in re.findall(r'\w+', t) if len(w) >= 3]


def _ta_sama_odmiana(a: str, b: str) -> bool:
    """Ten sam przedmiot w innym przypadku („prawa bankowego” / „prawo bankowe”):
    wyrazy parami różnią się najwyżej końcówką (do 3 liter). Czteroliterowy
    prefiks sam nie wystarcza — „o kredycie konsolidacyjnym” to nie „o kredycie
    konsumenckim” (przegląd Astry, 28.10.2026)."""
    wa, wb = _wyrazy(a), _wyrazy(b)
    if len(wa) != len(wb) or len(wa) < 2:
        return False
    for x, y in zip(wa, wb):
        n = 0
        while n < min(len(x), len(y)) and x[n] == y[n]:
            n += 1
        if n < max(4, min(len(x), len(y)) - 3):
            return False
    return True


async def _akt_z_tytulu(tekst: str) -> dict | str | None:
    """Słownik aktu dla tytułu ustawy, komunikat odmowy (str) albo None, gdy tekst
    nie wygląda na tytuł (np. nieznany skrót)."""
    q = _przedmiot(tekst)
    if len(q) < 8 or not (q.startswith("o ") or " " in q):
        return None
    kat = await _katalog_ustaw()
    # data z cytatu („ustawy z dnia 29 sierpnia 1997 r. o ochronie danych osobowych”)
    # rozstrzyga: ten sam przedmiot ma też ustawa z 2018 r. — bez filtra trafilibyśmy w nią
    data = re.search(r'z\s+dnia\s+(\d{1,2}\s+\S+\s+\d{4})', tekst or "", re.IGNORECASE)
    if data:
        dz = re.sub(r'\s+', ' ', data.group(1)).lower()
        kat = [x for x in kat
               if re.search(rf'z dnia (?<!\d){re.escape(dz)}\b', re.sub(r'\s+', ' ', (x.get("title") or "")).lower())]
        if not kat:
            return (f"❌ Wśród obowiązujących ustaw nie ma ustawy z dnia {data.group(1)} r. o tym "
                    f"przedmiocie („{tekst}”) — mogła zostać uchylona. Sprawdź adres Dz.U.; "
                    f"narzędzie podaje brzmienie obowiązujących ustaw.")
    dokladne = [x for x in kat if _przedmiot(x.get("title")) == q]
    if not dokladne:
        dokladne = [x for x in kat if _ta_sama_odmiana(q, _przedmiot(x.get("title")))]
    if not dokladne and data:
        return (f"❌ Wśród obowiązujących ustaw nie ma ustawy z dnia {data.group(1)} r. o tym "
                f"przedmiocie („{tekst}”) — mogła zostać uchylona. Sprawdź adres Dz.U.; "
                f"narzędzie podaje brzmienie obowiązujących ustaw.")
    if len(dokladne) == 1:
        x = dokladne[0]
        return dict(pub="DU", year=x["year"], pos=x["pos"],
                    name=re.sub(r'\s+', ' ', x.get("title") or "").strip().rstrip('.'))
    if len(dokladne) > 1:
        kand = dokladne
    else:
        rq = set(_rdzenie(q))
        kand = sorted((x for x in kat if rq & set(_rdzenie(_przedmiot(x.get("title"))))),
                      key=lambda x: -len(rq & set(_rdzenie(_przedmiot(x.get("title"))))))[:5]
        if not kand:
            return None
    lista = "; ".join(f"{(x.get('title') or '')[:110]} — Dz.U. {x['year']} poz. {x['pos']}" for x in kand[:5])
    return (f"❌ Nie da się jednoznacznie ustalić ustawy dla „{tekst}”. Kandydaci: {lista}. "
            f"Wskaż akt adresem Dz.U., np. 'art. 1 Dz.U. {kand[0]['year']} poz. {kand[0]['pos']}'.")


# --- Rozporządzenie po tytule (wyszukiwarka ELI) ---
# „rozporządzenia Ministra Sprawiedliwości z dnia 22 października 2015 r. w sprawie opłat
# za czynności adwokackie”. Obowiązujących rozporządzeń jest ponad 20 tys., więc zamiast
# katalogu pytamy wyszukiwarkę ELI fragmentem tytułu („w sprawie …”). Przechodzi tylko
# rozporządzenie o identycznym przedmiocie, nie zmieniające; data i organ z cytatu,
# jeśli są, muszą się zgadzać. Kilka obowiązujących trafień — odmowa z kandydatami.
_MIES_PREFIKSY = ("stycz", "lut", "mar", "kwie", "maj", "czerw", "lip", "sierp", "wrze", "paźdz", "listop", "grud")
_ROZP_RE = re.compile(r'^rozporządze\w*\s+(?P<organ>.*?)\s*(?:z\s+dnia\s+(?P<dzien>\d{1,2})\s+(?P<mies>\S+)\s+'
                      r'(?P<rok>\d{4})\s*r?\.?\s*)?w\s+sprawie\s+(?P<przedmiot>.+)$', re.IGNORECASE)
_rozporzadzenia: dict[str, tuple[float, dict | str | None]] = {}


def _norm_tyt(t: str) -> str:
    return re.sub(r'[\s„”"«».,;:]+', ' ', (t or "").lower()).strip()


def _data_tytulu(dzien: str, mies: str, rok: str) -> tuple[int, int, int] | None:
    m = next((i + 1 for i, p in enumerate(_MIES_PREFIKSY) if mies.lower().startswith(p)), None)
    return (int(rok), m, int(dzien)) if m else None


async def _rozporzadzenie_z_tytulu(tekst: str) -> dict | str | None:
    t = re.sub(r'\s+', ' ', tekst or "").strip().rstrip('.')
    m = _ROZP_RE.match(t)
    if not m:
        return None
    klucz = t.lower()
    if klucz in _rozporzadzenia and time.time() - _rozporzadzenia[klucz][0] < _KATALOG_TTL:
        return _rozporzadzenia[klucz][1]
    przedmiot = _norm_tyt(re.split(r'\s*\(Dz\.\s*U\.', m.group("przedmiot"))[0])
    data = m.group("rok") and _data_tytulu(m.group("dzien"), m.group("mies"), m.group("rok"))
    organ = [w[:5] for w in _norm_tyt(m.group("organ")).split() if len(w) > 2]
    # do wyszukiwarki tylko początek przedmiotu bez znaków specjalnych („1,5%” — % działa
    # w ELI jak symbol wieloznaczny i zapytanie nie trafia); pełne porównanie niżej
    zapytanie = re.split(r'[^\w\s]', m.group("przedmiot"))[0].strip()[:150]
    if len(zapytanie) < 12:
        zapytanie = " ".join(w for w in m.group("przedmiot").split() if w.isalpha())[:150]
    items, off = [], 0
    async with httpx.AsyncClient(timeout=60, headers=_HEADERS) as c:
        while True:
            r = await c.get("https://api.sejm.gov.pl/eli/acts/search", params={
                "publisher": "DU", "type": "Rozporządzenie", "title": zapytanie,
                "limit": 500, "offset": off})
            r.raise_for_status()
            it = r.json().get("items", [])
            items += it
            if len(it) < 500 or off > 5000:
                break
            off += 500
    pasuje = []
    for x in items:
        tyt = re.sub(r'\s+', ' ', x.get("title") or "").strip()
        mt = re.match(r'Rozporządzenie\s+(?P<organ>.*?)\s+z dnia\s+(?P<dzien>\d{1,2})\s+(?P<mies>\S+)\s+'
                      r'(?P<rok>\d{4})\s*r\.\s*w sprawie\s+(?P<przedmiot>.+)$', tyt.rstrip('.'))
        if not mt or _norm_tyt(mt.group("przedmiot")) != przedmiot:
            continue
        if data and _data_tytulu(mt.group("dzien"), mt.group("mies"), mt.group("rok")) != data:
            continue
        organ_x = [w[:5] for w in _norm_tyt(mt.group("organ")).split() if len(w) > 2]
        if organ and organ != organ_x:
            continue
        pasuje.append(x)
    obow = [x for x in pasuje if x.get("inForce") == "IN_FORCE" or x.get("status") in (
        "obowiązujący", "akt posiada tekst jednolity")]
    if len(obow) == 1:
        x = obow[0]
        wynik = await _akt_z_adresu(f"DU/{x['year']}/{x['pos']}")
    elif len(obow) > 1:
        lista = "; ".join(f"{x['title'][:120]} — Dz.U. {x['year']} poz. {x['pos']}" for x in obow[:5])
        wynik = (f"❌ Kilka obowiązujących rozporządzeń pasuje do „{t}”: {lista}. Podaj datę rozporządzenia "
                 f"albo adres Dz.U., np. '§ 1 Dz.U. {obow[0]['year']} poz. {obow[0]['pos']}'.")
    elif pasuje:
        lista = "; ".join(f"{x['title'][:100]} — Dz.U. {x['year']} poz. {x['pos']} ({x.get('status')})"
                          for x in pasuje[:3])
        wynik = (f"❌ Rozporządzenie „{t}” nie obowiązuje: {lista}. Narzędzie podaje brzmienie "
                 f"obowiązujących aktów; brzmienie z dawnego dnia poda verify_article z na_dzien "
                 f"i adresem Dz.U.")
    else:
        wynik = (f"❌ Nie znalazłem w ELI rozporządzenia o tytule „{t}” (przedmiot, data i organ muszą "
                 f"się zgadzać z tytułem). Sprawdź tytuł albo wskaż adres Dz.U.")
    _rozporzadzenia[klucz] = (time.time(), wynik)
    return wynik


# --- Dowolny akt UE (numer, CELEX, traktaty) ---
# „dyrektywy 93/13/EWG”, „rozporządzenia (WE) nr 593/2008”, „rozporządzenia 2016/679”,
# „decyzji 2011/753/UE”, „CELEX 32019L0770”, „TFUE”, „Karty praw podstawowych”.
# Z numeru powstaje kilku kandydatów CELEX (kolejność rok/numer zależy od typu
# i epoki: dyrektywy rok/numer, rozporządzenia do 2014 numer/rok, od 2015 rok/numer).
# Kandydat przechodzi tylko wtedy, gdy CELLAR zna go jako akt tego typu, a polski
# tytuł zawiera numer w zapisie z cytatu. Dwa trafienia albo zero — odmowa. Nie zgadujemy.
_TRAKTATY_UE = (
    (r'tfue|tfeu|traktat\w*\s+o\s+funkcjonowaniu\s+unii(?:\s+europejskiej)?', "12016E/TXT",
     "Traktat o funkcjonowaniu Unii Europejskiej"),
    (r'tue|teu|traktat\w*\s+o\s+unii\s+europejskiej', "12016M/TXT",
     "Traktat o Unii Europejskiej"),
    (r'kpp(?:\s*ue)?|kart\w*\s+praw\s+podstawowych(?:\s+unii(?:\s+europejskiej)?|\s+ue)?', "12016P/TXT",
     "Karta praw podstawowych Unii Europejskiej"),
)
_TYP_UE = (("rozporządz", "R", "REG"), ("dyrektyw", "L", "DIR"),
           ("decyzji ramowej", "F", "DEC"), ("decyzja ramowa", "F", "DEC"), ("decyzj", "D", "DEC"))
_NUMER_UE_RE = re.compile(r'(?<![\d/])(\d{2,4})\s*/\s*(\d{1,4})(?![\d])')
_CELEX_RE = re.compile(r'(?:celex[:\s]*)?\b([0-9]\d{4}[A-Z]{1,2}\d{4})\b', re.IGNORECASE)
_akty_ue: dict[str, tuple[float, dict | str]] = {}


def _rok_ue(r: str) -> int | None:
    n = int(r)
    if len(r) == 4:
        return n if 1952 <= n <= _dt.date.today().year else None
    if len(r) == 2:
        return 1900 + n if n >= 52 else 2000 + n
    return None


def _kandydaci_celex(sektor: str, a: str, b: str) -> list[str]:
    """Numer „a/b” z cytatu → kandydaci CELEX (rok, numer) bez powtórzeń."""
    pary = []
    if sektor == "R":
        # od 2015 r. rok/numer („2016/679”), wcześniej numer/rok („593/2008”, „1408/71”)
        pary += [(b, a), (a, b)] if not (len(a) == 4 and int(a) >= 2015) else [(a, b), (b, a)]
    else:
        pary += [(a, b), (b, a)]
    out = []
    for rok, nr in pary:
        r = _rok_ue(rok)
        if r and len(nr) <= 4:
            c = f"3{r}{sektor}{int(nr):04d}"
            if c not in out:
                out.append(c)
    return out


def _nazwa_ue(tytul: str) -> str:
    """Pełny tytuł z CELLAR → nazwa do nagłówka (rodzaj, numer, data, przedmiot ≤ 90 zn.)."""
    t = re.sub(r'\s+', ' ', tytul).strip().rstrip('.')
    # „2011/753/UE: Decyzja Komisji …” — numer przed dwukropkiem powtarza się w tytule
    t = re.sub(r'^\d{2,4}/\d{1,4}/[A-ZĄĆĘŁŃÓŚŹŻ]+:\s*', '', t)
    m = re.match(r'(.+? z dnia \d{1,2} \S+ \d{4} r\.)\s*(.*)', t)
    if not m:
        return t[:160]
    glowa, reszta = m.group(1), m.group(2)
    reszta = re.split(r'\s*\((?:Tekst mający znaczenie dla EOG|Dz\.U\.)', reszta)[0]
    return glowa + (" " + (reszta if len(reszta) <= 90 else reszta[:90].rsplit(' ', 1)[0] + " …")
                    if reszta else "")


async def _metadane_ue(celexy: list[str]) -> dict[str, dict]:
    if not celexy:
        return {}
    lista = ",".join(f'"{c}"' for c in celexy)
    wiersze = await _sparql(
        "PREFIX cdm: <http://publications.europa.eu/ontology/cdm#>\n"
        "SELECT ?celex ?title ?inforce ?type ?eif ?eov WHERE { ?w cdm:resource_legal_id_celex ?celex . "
        f"FILTER(STR(?celex) IN ({lista})) "
        "OPTIONAL { ?w cdm:resource_legal_in-force ?inforce } "
        "OPTIONAL { ?w cdm:resource_legal_date_entry-into-force ?eif } "
        "OPTIONAL { ?w cdm:resource_legal_date_end-of-validity ?eov } "
        "OPTIONAL { ?w cdm:work_has_resource-type ?type } "
        "OPTIONAL { ?e cdm:expression_belongs_to_work ?w ; cdm:expression_title ?title ; "
        "cdm:expression_uses_language <http://publications.europa.eu/resource/authority/language/POL> } }")
    out: dict[str, dict] = {}
    for w in wiersze:
        d = out.setdefault(w["celex"], {"tytul": "", "obowiazuje": None, "typy": set(),
                                        "od": None, "do": None})
        for pole, klucz in (("eif", "od"), ("eov", "do")):
            try:
                x = _dt.date.fromisoformat((w.get(pole) or "")[:10])
            except ValueError:
                continue
            # kilka dat wejścia w życie (przepisy stosowane etapami) — najwcześniejsza;
            # kilka dat utraty mocy — najpóźniejsza
            if d[klucz] is None or (x < d[klucz] if klucz == "od" else x > d[klucz]):
                d[klucz] = x
        # tytuły CELLAR mają twarde spacje („1985\xa0r.”) — jeden zwykły odstęp
        d["tytul"] = d["tytul"] or re.sub(r'\s+', ' ', w.get("title", "")).strip()
        if w.get("inforce") in ("1", "true"):
            d["obowiazuje"] = True
        elif w.get("inforce") in ("0", "false") and d["obowiazuje"] is None:
            d["obowiazuje"] = False
        if w.get("type"):
            d["typy"].add(w["type"].rsplit("/", 1)[-1])
    return out


def _wynik_ue(celex: str, meta: dict, nazwa: str | None = None,
              dzien: _dt.date | None = None) -> dict | str:
    if dzien:
        n = nazwa or _nazwa_ue(meta.get("tytul") or "") or f"CELEX {celex}"
        if meta.get("od") and dzien < meta["od"]:
            return (f"❌ {n} (CELEX {celex}) wszedł w życie {meta['od']:%d.%m.%Y} — "
                    f"{dzien:%d.%m.%Y} jeszcze nie obowiązywał.")
        if meta.get("do") and meta["do"].year < 9999 and dzien > meta["do"]:
            return (f"❌ {n} (CELEX {celex}) obowiązywał do {meta['do']:%d.%m.%Y} — "
                    f"{dzien:%d.%m.%Y} już nie obowiązywał.")
    if not meta.get("tytul") and not nazwa:
        return (f"❌ Akt CELEX {celex} nie ma w CELLAR polskiej wersji językowej (akty sprzed "
                f"1.05.2004 r. spoza polskiego wydania specjalnego Dz.U. UE) — narzędzie podaje "
                f"tylko tekst polski.")
    if meta.get("obowiazuje") is False and not dzien:
        do = f" (obowiązywał do {meta['do']:%d.%m.%Y})" if meta.get("do") else ""
        return (f"❌ {nazwa or _nazwa_ue(meta['tytul'])} (CELEX {celex}) wg CELLAR nie obowiązuje{do} "
                f"— narzędzie podaje brzmienie obowiązujących aktów; brzmienie z dnia, w którym "
                f"obowiązywał, poda verify_article z na_dzien.")
    return dict(celex=celex, name=nazwa or _nazwa_ue(meta["tytul"]) or f"CELEX {celex}")


async def _akt_ue_z_cytatu(tekst: str, dzien: _dt.date | None = None) -> dict | str | None:
    """Słownik aktu UE (jak w EU_ACTS), komunikat odmowy (str) albo None,
    gdy tekst nie wskazuje aktu UE."""
    t = re.sub(r'\s+', ' ', tekst or "").strip().rstrip('.')
    nisko = t.lower()
    klucz = f"{nisko}|{dzien}"
    if klucz in _akty_ue and time.time() - _akty_ue[klucz][0] < _KATALOG_TTL:
        return _akty_ue[klucz][1]

    wynik: dict | str | None = None
    for wzor, celex, nazwa in _TRAKTATY_UE:
        if re.fullmatch(rf'(?:art\.\s*)?{wzor}(?:\s*\(.*\))?', nisko):
            wynik = dict(celex=celex, name=nazwa)
            break
    if wynik is None and (m := _CELEX_RE.search(t)):
        celex = m.group(1).upper()
        meta = (await _metadane_ue([celex])).get(celex)
        wynik = (_wynik_ue(celex, meta, dzien=dzien) if meta
                 else f"❌ CELLAR nie zna aktu o numerze CELEX {celex}.")
    if wynik is None:
        typ = next(((sek, cd) for slowo, sek, cd in _TYP_UE if slowo in nisko), None)
        num = _NUMER_UE_RE.search(t)
        # „rozporządzenia … Dz.U. 2025 poz. 1899” to akt polski — ten tor go nie bierze
        if typ and num and not _ADRES_DZU_RE.search(t):
            sektor, kod_typu = typ
            a, b = num.group(1), num.group(2)
            kand = _kandydaci_celex(sektor, a, b)
            meta = await _metadane_ue(kand)
            zapis = re.compile(rf'(?<![\d/]){re.escape(a)}/{re.escape(b)}(?![\d])')
            trafione = [c for c in kand if c in meta
                        and any(x.startswith(kod_typu) for x in meta[c]["typy"])
                        and zapis.search(meta[c]["tytul"] or "")]
            if not trafione:
                # stare polskie tytuły dyrektyw nie mają numeru („Dyrektywa Rady z dnia
                # 25 lipca 1985 r. …” = 85/374/EWG): wtedy jedyny kandydat tego rodzaju,
                # którego rok z CELEX-u to rok przyjęcia w tytule albo następny (87/102/EWG
                # przyjęta 22.12.1986 r., numer z roku publikacji)
                trafione = [c for c in kand if c in meta
                            and any(x.startswith(kod_typu) for x in meta[c]["typy"])
                            and re.search(rf'z dnia \d{{1,2}} \S+ (?:{c[1:5]}|{int(c[1:5]) - 1}) r\.',
                                          meta[c]["tytul"] or "")]
                trafione = trafione if len(trafione) == 1 else []
            if len(trafione) == 1:
                wynik = _wynik_ue(trafione[0], meta[trafione[0]], dzien=dzien)
            elif len(trafione) > 1:
                wynik = ("❌ Numer " + f"{a}/{b} wskazuje więcej niż jeden akt UE: "
                         + "; ".join(f"{c} — {_nazwa_ue(meta[c]['tytul'])}" for c in trafione)
                         + ". Podaj CELEX, np. 'art. 1 CELEX " + trafione[0] + "'.")
            else:
                wynik = (f"❌ Nie znalazłem w CELLAR aktu UE „{t}” (sprawdzone CELEX: "
                         f"{', '.join(kand) or 'brak'}). Sprawdź rodzaj i numer aktu albo podaj CELEX.")
    if wynik is not None:
        _akty_ue[klucz] = (time.time(), wynik)
    return wynik


async def _odpowiedz_eu(info: dict, art: str, ustep: str | None, ref: str,
                        dzien: _dt.date | None = None) -> str:
    """Artykuł aktu UE z najnowszej wersji skonsolidowanej obowiązującej dziś
    (albo we wskazanym dniu), a gdy jej nie ma — z tekstu pierwotnego, z jawną
    informacją o zmianach."""
    dzis = dzien or _dt.date.today()
    wersja = await _wersja_eu(info["celex"], dzien)
    skons = wersja["celex"] != info["celex"]
    uwaga_pobrania = ""
    text = await _fetch_eu({**info, "celex": wersja["celex"]})
    if text is None and skons:
        uwaga_pobrania = (f"⚠ Nie udało się pobrać wersji skonsolidowanej {wersja['celex']} "
                          f"— poniżej tekst pierwotny.\n")
        skons = False
        text = await _fetch_eu(info)
    if text is None:
        return (f"❌ Nie udało się pobrać {info['name']} ani z CELLAR, ani z EUR-Lex (brak tekstu "
                f"HTML w wersji polskiej albo chwilowa blokada EUR-Lexu)")
    celex = wersja["celex"] if skons else info["celex"]
    opis_wersji = (f"tekst skonsolidowany {celex}, stan na {wersja['data']:%d.%m.%Y}"
                   if skons else f"tekst pierwotny {celex}")

    art_text = extract_eu_article(text, art, None)
    if not art_text:
        return (f"❌ {ref} nie znaleziony w {info['name']} ({opis_wersji}). "
                f"Sprawdź numer artykułu.")
    kody = sorted({k for k in _ZNACZNIK_EU_RE.findall(art_text) if k and k != "B"})
    result = re.sub(r' {2,}', ' ', _ZNACZNIK_EU_RE.sub(' ', art_text)).strip()
    if ustep:
        # bez „Artykuł N” na początku: inaczej „6 1.” wygląda jak indeks „§ 1 1.”
        result = _cut_ustep(re.sub(r'^Artykuł\s+\S+\s*', '', result), ustep)
        if not result:
            return (f"❌ {ref} nie znaleziony w {info['name']} ({opis_wersji}). "
                    f"Sprawdź numer ustępu.")

    zm = wersja["zmieniajace"]
    po = [c for c, d in zm if d and d <= dzis and (not skons or d > wersja["data"])]
    przyszle = [f"{c} (od {d:%d.%m.%Y})" for c, d in zm if d and d > dzis]
    if wersja["blad"]:
        aktualnosc = ("nieustalona — CELLAR nie odpowiedział na pytanie o wersje "
                      "skonsolidowane i akty zmieniające; to tekst pierwotny, mógł zostać zmieniony")
        akt_kod = "nieustalona_blad_cellar"
    elif po:
        aktualnosc = (f"nieustalona — {'po dacie tej wersji ' if skons else ''}weszły w życie "
                      f"akty zmieniające: {', '.join(po)}; sprawdź, czy dotyczą tego artykułu")
        akt_kod = f"nieustalona_{len(po)}_aktow_zmieniajacych_po_wersji"
    else:
        aktualnosc = ("wg CELLAR " + (f"po dacie tej wersji ({wersja['data']:%d.%m.%Y}) "
                                      if skons else "")
                      + "nie wszedł w życie żaden akt zmieniający")
        akt_kod = "potwierdzona_wg_cellar"
    if przyszle:
        aktualnosc += (f". Zmiany wchodzące w życie po {dzis:%d.%m.%Y}: " if dzien
                       else ". Zmiany jeszcze nieobowiązujące: ") + ", ".join(przyszle)
    if dzien:
        aktualnosc = f"brzmienie na dzień {dzien:%d.%m.%Y} — " + aktualnosc

    skad = (_zrodlo.get(f"EU:{celex}") or ("EUR-Lex",))[0]
    if skons:
        legenda = _legenda_zmian(text)
        naglowek = (f"(źródło: {skad}, {opis_wersji}, wersja polska)\n"
                    f"⚠ TEKST SKONSOLIDOWANY — nieurzędowy (służy celom informacyjnym); "
                    f"wiążące są akty w Dz.U. UE: {info['celex']} i akty zmieniające")
        if kody:
            naglowek += ("\nW tym artykule są fragmenty zmienione: "
                         + "; ".join(f"{k} = {legenda.get(k, 'sprostowanie' if k.startswith('C') else 'akt zmieniający')}"
                                     for k in kody))
        cytuj = f"{info['name']}, {opis_wersji} (nieurzędowy)"
    else:
        naglowek = f"(źródło: {skad}, CELEX {celex} — tekst pierwotny z Dz.U. UE, wersja polska)"
        cytuj = f"{info['name']}, tekst pierwotny {celex}"
    return (f"{'📄' if skons else '📜'} **{info['name']}**, {ref}\n{uwaga_pobrania}{naglowek}\n"
            f"Aktualność: {aktualnosc}\n\n{result}\n\n"
            f"[dla modelu] zrodlo={'tekst_skonsolidowany' if skons else 'tekst_pierwotny_dz_u_ue'}; "
            f"wersja={celex}; aktualnosc={akt_kod}; cytuj_jako=„{cytuj}”; "
            f"nie_nazywaj_tekstem_urzedowym={'tak' if skons else 'nie_dotyczy'}"
            + (f"; na_dzien={dzien.isoformat()}" if dzien else ""))


async def verify_article(citation: str) -> str:
    """Zwraca dokładne brzmienie cytowanego przepisu ze źródła oficjalnego.
    Format: 'art. N [ust. M] KOD' (np. 'art. 45 u.k.k.', 'art. 28 ust. 3 RODO')."""
    parsed = parse_citation(citation)
    if not parsed:
        return (f"❌ Nierozpoznany format: '{citation}'\n"
                f"Użyj: 'art. N [ust. M] KOD' — np. 'art. 45 u.k.k.'\n"
                f"Lista kodów: list_acts().")
    act, art, ustep = parsed["act"], parsed["art"], parsed["ustep"]
    # etykieta jak w cytacie: § dla paragrafów, indeks z powrotem jako górny (§ 1¹)
    jedn = "§" if re.search(r'\d\S*\s*§', citation) else "ust."
    ust_ety = ustep and re.sub(
        r'\[(\w+)\]', lambda x: x.group(1).translate(str.maketrans(
            "0123456789abcdefghijklmnoprstuvwxyz", "⁰¹²³⁴⁵⁶⁷⁸⁹ᵃᵇᶜᵈᵉᶠᵍʰⁱʲᵏˡᵐⁿᵒᵖʳˢᵗᵘᵛʷˣʸᶻ")), ustep)
    glowna = "§" if citation.strip().startswith("§") else "art."
    ref = f"{glowna} {art}" + (f" {jedn} {ust_ety}" if ustep else "")
    pl_key = _resolve(act, PL_ACTS)
    eu_key = _resolve(act, EU_ACTS)

    if pl_key:
        info = PL_ACTS[pl_key]
        try:
            return await _odpowiedz_pl(info, art, ustep, ref)
        except httpx.TimeoutException:
            return f"❌ Timeout pobierania {info['name']} z api.sejm.gov.pl"

    if eu_key:
        info = EU_ACTS[eu_key]
        try:
            return await _odpowiedz_eu(info, art, ustep, ref)
        except httpx.TimeoutException:
            return f"❌ Timeout pobierania {info['name']} z EUR-Lex"

    try:
        info_ue = await _akt_ue_z_cytatu(act)
    except httpx.HTTPError:
        return f"❌ Nie udało się ustalić aktu UE „{act}” w CELLAR (Urząd Publikacji UE)"
    if isinstance(info_ue, str):
        return info_ue
    if info_ue:
        try:
            return await _odpowiedz_eu(info_ue, art, ustep, ref)
        except httpx.TimeoutException:
            return f"❌ Timeout pobierania {info_ue['name']} z EUR-Lex"

    try:
        info = await _akt_z_adresu(act)
    except httpx.HTTPError:
        return f"❌ Nie udało się pobrać metadanych aktu {act} z api.sejm.gov.pl"
    if info is None:
        try:
            info = await _rozporzadzenie_z_tytulu(act)
        except httpx.HTTPError:
            return f"❌ Nie udało się przeszukać rozporządzeń w api.sejm.gov.pl"
    if info is None:
        try:
            info = await _akt_z_tytulu(act)
        except httpx.HTTPError:
            return f"❌ Nie udało się pobrać katalogu ustaw z api.sejm.gov.pl"
    if isinstance(info, str):
        return info
    if info:
        try:
            wynik = await _odpowiedz_pl(info, art, ustep, ref)
        except httpx.TimeoutException:
            return f"❌ Timeout pobierania {info['name']} z api.sejm.gov.pl"
        # rozporządzenie zacytowane jako „art. N”: treść to „§ N.” — etykieta jak w źródle
        if glowna == "art." and re.search(rf'(?m)^§ {re.escape(art)}\.', wynik) \
                and not re.search(rf'(?m)^Art\. {re.escape(art)}\.', wynik):
            wynik = wynik.replace(f"**, {ref}", f"**, § {ref[len('art. '):]}", 1)
        return wynik

    known = ", ".join(dict.fromkeys(list(PL_ACTS) + list(EU_ACTS)))
    return (f"❌ Nieznany kod aktu: '{act}'\nObsługiwane: {known}\n"
            f"Dowolną ustawę można wskazać adresem Dz.U., np. 'art. 5 Dz.U. 2024 poz. 1061', "
            f"a akt UE numerem albo CELEX-em, np. 'art. 6 ust. 1 dyrektywy 93/13/EWG', "
            f"'art. 4 rozporządzenia (WE) nr 593/2008', 'art. 267 TFUE', 'art. 1 CELEX 32019L0770'.")


def list_acts() -> str:
    """Lista obsługiwanych kodów aktów z pełnymi nazwami."""
    pl = "\n".join(f"  {k:<16} → {v['name']}" for k, v in PL_ACTS.items())
    eu = "\n".join(f"  {k:<16} → {v['name']}" for k, v in EU_ACTS.items())
    return ("📚 Obsługiwane kody aktów\n\n"
            f"Prawo PL (api.sejm.gov.pl):\n{pl}\n\n"
            f"Prawo UE (EUR-Lex, PL):\n{eu}")
