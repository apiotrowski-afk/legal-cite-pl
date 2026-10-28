"""Regresja uwag z przeglądu kodu (Astra, 28.10.2026) — bez sieci, na atrapach.

1. Wycięcie nowego brzmienia zdania w HTML zostawiało niedomknięty odnośnik,
   a _strip_html usuwa odnośnik do najbliższego </a> — znikała obowiązująca treść.
2. Etykieta „I)” była pomijana także w treści („załącznik I)”).
3. Ustawa po adresie Dz.U., która jeszcze nie weszła w życie, była przyjmowana.
4. Czteroliterowe rdzenie: „o kredycie konsolidacyjnym” → ustawa o kredycie konsumenckim.
5. Rozstrzygnięty odnośnik zdania maskował inne, nierozstrzygnięte wystąpienie.
6. Data „6 lutego 2007” pasowała do tytułu z „16 lutego 2007”.

    python testy/przeglad_astra.py
"""
import asyncio, datetime, pathlib, sys, httpx
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from legal_cite import core, pdf_tj

bledy = 0


def sprawdz(ok: bool, opis: str) -> None:
    global bledy
    bledy += not ok
    print("ok " if ok else "ZLE", opis)


MAPA = {"5": "Zdanie pierwsze w tym brzmieniu obowiązuje do wejścia w życie zmiany, o której mowa w odnośniku 6.",
        "6": "Zdanie pierwsze ze zmianą wprowadzoną przez ustawę (Dz. U. poz. 1), która wejdzie w życie "
             "z dniem 1 października 2029 r.",
        "7": "W brzmieniu ustalonym przez ustawę (Dz. U. poz. 2), która weszła w życie z dniem 1 stycznia 2021 r."}


def a(n):  # odnośnik w budowie źródła: <sup>, tooltip ze spanami, zamknięcie wielkimi literami
    return (f'<a class="gloss-link" href="#"><sup>{n})</sup><span class="tooltip-text">'
            f'<span>{MAPA.get(str(n), "x")}</span></span></A>')


# 1
H = (f"<p>Stare zdanie.{a(5)} Nowe zdanie.{a(6)} Obowiązujący tekst dalej.{a(7)} Koniec akapitu.</p>")
frag, _ = core._wybierz_zdania_html(H, MAPA, datetime.date(2026, 10, 28), [])
t = core._strip_html(frag)
sprawdz("Stare zdanie." in t and "Obowiązujący tekst dalej." in t and "Koniec akapitu." in t
        and "Nowe zdanie" not in t, f"1. HTML: obowiązująca treść za odnośnikiem zostaje: {t!r}")

# 1b: odnośnik B jako goły „<SUP>157)</SUP>” bez dymka (art. 505 k.p.k., t.j. 2024/37)
H2 = (f"<p>Stare zdanie.{a(5)}<B CLASS=\"b\">Nowe zdanie. </B><SUP>6)</SUP></p><p>Dalej.</p>")
frag, ok_ = core._wybierz_zdania_html(H2, MAPA, datetime.date(2026, 10, 28), [])
t = core._strip_html(frag)
sprawdz("Stare zdanie." in t and "Nowe zdanie" not in t and "Dalej." in t and ok_ == {"5"},
        f"1b. goły <SUP> jako odnośnik B: {t!r}")

# 2
sprawdz("i" in pdf_tj.tokeny("wymogi (załącznik I) rozporządzenia"), "2. „załącznik I)” — liczba rzymska w treści zostaje")
sprawdz("i" not in pdf_tj.tokeny("1)I) Niniejsza ustawa"), "2. „1)I)” — etykieta odnośnika pomijana")
sprawdz(pdf_tj.tokeny("(załącznik I) do") != pdf_tj.tokeny("(załącznik II) do"), "2. zmiana I → II widoczna w porównaniu")


# 3
def handler(req):
    if str(req.url).endswith("/DU/2099/1"):
        return httpx.Response(200, json={"type": "Ustawa", "title": "Ustawa z dnia 1 stycznia 2099 r. o przyszłości",
                                         "status": "oczekujący na wejście w życie", "entryIntoForce": "2099-06-01"})
    return httpx.Response(404, json={})


class Mock(httpx.AsyncClient):
    def __init__(self, *a_, **k):
        k["transport"] = httpx.MockTransport(handler)
        super().__init__(*a_, **k)


prawdziwy = core.httpx.AsyncClient
core.httpx.AsyncClient = Mock
w = asyncio.run(core._akt_z_adresu("Dz.U. 2099 poz. 1"))
core.httpx.AsyncClient = prawdziwy
sprawdz(isinstance(w, str) and "jeszcze nie weszła" in w, f"3. ustawa przed wejściem w życie → odmowa: {str(w)[:80]!r}")

# 4
sprawdz(core._ta_sama_odmiana("prawa bankowego", "prawo bankowe"), "4. „prawa bankowego” = „prawo bankowe”")
sprawdz(not core._ta_sama_odmiana("o kredycie konsolidacyjnym", "o kredycie konsumenckim"),
        "4. „o kredycie konsolidacyjnym” ≠ „o kredycie konsumenckim”")

# 5
wyb = {"przypisy": MAPA, "dzis": datetime.date(2026, 10, 28), "uwagi": [], "niejednoznaczne": False, "zdania_ok": set()}
t1 = pdf_tj._wybierz_zdania("Stare.[^5] Nowe.[^6] Dalej.", wyb)
t2 = pdf_tj._wybierz_zdania("Stare drugie.[^5] Nowe drugie bez odnośnika B.", wyb)
sprawdz("[^5]" not in t1 and "[^5]" in t2, "5. rozstrzygnięte wystąpienie znika, nierozstrzygnięte zostaje (odmowa)")
sprawdz(core._zdania_dwa_brzmienia(MAPA, pdf_tj._PRZYPIS_RE.findall(t1 + t2)) != [],
        "5. nierozstrzygnięte wystąpienie daje niejednoznaczność")

# 6
KAT = [{"title": "Ustawa z dnia 16 lutego 2007 r. o ochronie konkurencji i konsumentów", "year": 2007, "pos": 331}]


async def katalog():
    return KAT


core._katalog_ustaw = katalog
w = asyncio.run(core._akt_z_tytulu("ustawy z dnia 6 lutego 2007 r. o ochronie konkurencji i konsumentów"))
sprawdz(isinstance(w, str) and "nie ma ustawy z dnia 6 lutego 2007" in w, f"6. 6 ≠ 16 lutego: {str(w)[:70]!r}")
w = asyncio.run(core._akt_z_tytulu("ustawy z dnia 16 lutego 2007 r. o ochronie konkurencji i konsumentów"))
sprawdz(isinstance(w, dict) and w["pos"] == 331, "6. 16 lutego 2007 → właściwa ustawa")

print("wszystko OK" if not bledy else f"{bledy} błędów")
sys.exit(1 if bledy else 0)
