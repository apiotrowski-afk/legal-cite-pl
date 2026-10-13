"""Jednostki wydrukowane z wyprzedzeniem (dodane, ale jeszcze nieobowiązujące) — bez sieci.

Tekst jednolity drukuje jednostki dodane nowelizacją, która jeszcze nie weszła
w życie; odnośnik „Dodany przez…” podaje datę. Art. 94 pkt 2c i art. 104¹
§ 1 pkt 10 k.p. w t.j. Dz.U. 2026 poz. 1245 obowiązują od 5.11.2026, a
narzędzie oddawało je wcześniej jako obowiązujące. Wybór brzmienia wg daty
działał tylko dla jednostek drukowanych dwa razy.

Akt i odnośniki poniżej są fikcyjne; daty w 2099 r., żeby test nie zależał
od dnia uruchomienia. Część „PDF” wymaga eli2md (drzewo jednostek).

    python testy/przyszle.py
"""
import datetime as dt
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from legal_cite import core, pdf_tj

PRZED, PO = dt.date(2099, 6, 30), dt.date(2099, 7, 1)
bledy = 0


def sprawdz(ok: bool, opis: str) -> None:
    global bledy
    bledy += not ok
    print("ok " if ok else "ZLE", opis)


# --- odnośniki ---------------------------------------------------------------
MAPA = {
    "1": "W brzmieniu ustalonym przez art. 1 pkt 1 ustawy z dnia 2 lutego 2099 r. o zmianie "
         "ustawy o rejestrze latarni (Dz. U. poz. 77), która wejdzie w życie z dniem 1 lipca 2099 r.",
    "2": "Ze zmianą wprowadzoną przez art. 3 ustawy z dnia 5 maja 2020 r. (Dz. U. poz. 900), "
         "która weszła w życie z dniem 1 stycznia 2021 r.",
    "3": "Dodany przez art. 1 pkt 2 ustawy, o której mowa w odnośniku 1.",
    "4": "Dodana przez art. 1 pkt 3 ustawy, o której mowa w odnośniku 1.",
    "5": "W brzmieniu ustalonym przez art. 1 pkt 4 ustawy, o której mowa w odnośniku 1.",
    "6": "Wejdzie w życie z dniem 1 lipca 2099 r.",
}
sprawdz(core._jeszcze_nie(MAPA, "3", PRZED) == (PO, True), "„Dodany…” przed datą: nie obowiązuje, dodany")
sprawdz(core._jeszcze_nie(MAPA, "4", PRZED) == (PO, True), "„Dodana…” przed datą")
sprawdz(core._jeszcze_nie(MAPA, "6", PRZED) == (PO, True), "„Wejdzie w życie…” przed datą")
sprawdz(core._jeszcze_nie(MAPA, "5", PRZED) == (PO, False), "„W brzmieniu ustalonym…” przed datą: nie dodany")
sprawdz(core._jeszcze_nie(MAPA, "3", PO) is None, "w dniu wejścia w życie już obowiązuje")
sprawdz(core._jeszcze_nie(MAPA, "2", PRZED) is None, "odnośnik z datą przeszłą")
sprawdz(core._jeszcze_nie(MAPA, None, PRZED) is None, "jednostka bez odnośnika")

# --- ścieżka PDF: drzewo jednostek z Markdown ---------------------------------
MD = """## Załącznik

##### Art. 1.

Latarnik jest obowiązany:

1) prowadzić dziennik latarni;

2)[^2] zgłaszać awarie światła;

2a)[^3] archiwizować zgłoszenia awarii;

3) (uchylony)

##### Art. 2.

[^3] § 1. Latarnik prowadzi rejestr mgieł.

§ 2. Rejestr mgieł jest jawny.

##### Art. 3.

§ 1. Latarnia świeci od zmierzchu do świtu.

§ 2.[^5] Minister może skrócić czas świecenia.

##### Art. 4.

§ 1. Latarnię maluje się co pięć lat.

§ 2.[^6] Kolor latarni ustala minister.

§ 3.[^4] Farba nie może zawierać ołowiu.

##### Art. 5.

Ustawa wchodzi w życie po upływie 14 dni od dnia ogłoszenia.

""" + "".join(f"[^{nr}]: {tresc}\n\n" for nr, tresc in MAPA.items())

try:
    import eli2md.tree  # noqa: F401
    jest_eli2md = True
except Exception:
    jest_eli2md = False
    print("--  eli2md niezainstalowany — część PDF pominięta")

if jest_eli2md:
    przypisy = pdf_tj.przypisy_md(MD)
    przed = {j.klucz: j for j in pdf_tj.jednostki_md(MD, przypisy, dzis=PRZED)[0]}
    po = {j.klucz: j for j in pdf_tj.jednostki_md(MD, przypisy, dzis=PO)[0]}
    a1 = przed["1"]
    sprawdz("archiwizować" not in a1.czysty() and "zgłaszać awarie" in a1.czysty()
            and "(uchylony)" in a1.czysty(), "PDF: dodany pkt 2a pominięty, reszta art. 1 bez zmian")
    sprawdz(any("pkt 2a" in u and "01.07.2099" in u for u in a1.uwagi) and not a1.niejednoznaczne,
            "PDF: uwaga o pominiętym pkt 2a z datą")
    sprawdz("archiwizować" in a1.pelny, "PDF: pełny tekst (do kontroli wierności) zawiera pkt 2a")
    sprawdz("archiwizować" in po["1"].czysty() and not po["1"].uwagi,
            "PDF: od dnia wejścia w życie pkt 2a jest w tekście, bez uwagi")
    sprawdz(core._jeszcze_nie(przypisy, przed["2"].wlasny_odnosnik, PRZED) == (PO, True),
            "PDF: cały art. 2 dodany — jeszcze nie obowiązuje")
    sprawdz(core._jeszcze_nie(przypisy, po["2"].wlasny_odnosnik, PO) is None,
            "PDF: art. 2 obowiązuje od dnia wejścia w życie")
    sprawdz(przed["3"].niejednoznaczne and "świeci od zmierzchu" in przed["3"].czysty(),
            "PDF: jedyne brzmienie § 2 z przyszłą datą i bez „Dodany” → odmowa (niejednoznaczne)")
    a4 = przed["4"]
    sprawdz("Kolor latarni" not in a4.czysty() and "ołowiu" not in a4.czysty()
            and "maluje się" in a4.czysty() and len(a4.uwagi) == 2,
            "PDF: § 2 („Wejdzie w życie…”) i § 3 („Dodana…”) pominięte")
    # odnośnik paragrafu nie datuje całego artykułu (art. 860 k.c.: „Dodany” przy § 3)
    sprawdz(a4.data is None and a4.wlasny_odnosnik is None
            and core._jeszcze_nie(przypisy, a4.wlasny_odnosnik, PRZED) is None,
            "PDF: odnośnik przy § 2 nie czyni całego art. 4 nieobowiązującym")
    sprawdz(not przed["5"].uwagi and przed["5"].czysty() == po["5"].czysty(),
            "PDF: artykuł bez odnośników bez zmian")


# --- ścieżka HTML: znaczniki jednostek źródła ---------------------------------
def odn(nr: str) -> str:
    return (f'<A class="gloss-link tooltip" href="#gloss-{nr}"><sup>{nr})</sup>'
            f'<span class="tooltip-text">{MAPA[nr]}</span></A>')


def jedn(typ: str, did: str, naglowek: str, tresc: str) -> str:
    return (f'<div class="unit unit_{typ} pro-text" id="x-{did}" data-id="{did}">'
            f'<h3><B>{naglowek}</B></h3><div class="pro-text">{tresc}</div></div>')


HTML = (
    jedn("arti", "arti_1", "Art.&nbsp;1.", "Latarnik jest obowiązany:"
         + jedn("pint", "pint_1", "1)", "prowadzić dziennik latarni;")
         + jedn("pint", "pint_2", "2)" + odn("2"), "zgłaszać awarie światła;")
         + jedn("pint", "pint_2a", "2a)" + odn("3"), "archiwizować zgłoszenia awarii;"))
    + jedn("arti", "arti_2", "Art.&nbsp;2." + odn("3"),
           jedn("para", "para_1", "§&nbsp;1.", "Latarnik prowadzi rejestr mgieł."))
    + jedn("arti", "arti_3", "Art.&nbsp;3.",
           jedn("para", "para_1", "§&nbsp;1.", "Latarnia świeci od zmierzchu do świtu.")
           + jedn("para", "para_2", "§&nbsp;2." + odn("5"), "Minister może skrócić czas świecenia."))
    + jedn("arti", "arti_4", "Art.&nbsp;4.",
           jedn("para", "para_1", "§&nbsp;1.", "Latarnię maluje się co pięć lat, o czym mowa w ustawie"
                + odn("1") + " o rejestrze latarni."))
)
KEY = "TEST:latarnie"
t1 = core.extract_pl_article_html(KEY, HTML, "1", None)
sprawdz(t1 is not None and "archiwizować" not in t1 and "zgłaszać awarie" in t1
        and "pkt 2a" in t1 and "01.07.2099" in t1, "HTML: dodany pkt 2a pominięty z uwagą")
try:
    core.extract_pl_article_html(KEY, HTML, "2", None)
    sprawdz(False, "HTML: cały art. 2 dodany — brak odmowy")
except core.JeszczeNieObowiazuje as e:
    sprawdz(e.dodany and e.data == PO, "HTML: cały art. 2 dodany → JeszczeNieObowiazuje z datą")
try:
    core.extract_pl_article_html(KEY, HTML, "3", None)
    sprawdz(False, "HTML: jedyne brzmienie § 2 z przyszłą datą — brak odmowy")
except core.Niejednoznaczne:
    sprawdz(True, "HTML: jedyne brzmienie § 2 z przyszłą datą i bez „Dodany” → Niejednoznaczne")
t4 = core.extract_pl_article_html(KEY, HTML, "4", None)
sprawdz(t4 is not None and "maluje się" in t4 and "⚠" not in t4,
        "HTML: odnośnik w środku zdania nie jest odnośnikiem jednostki")
uwagi: list[str] = []
art1 = HTML[:core._koniec_div(HTML, 0)]
caly = core._wybierz_podjednostki_html(art1, core._odnosniki(KEY, HTML), PO, uwagi)
sprawdz("archiwizować" in caly and not uwagi, "HTML: od dnia wejścia w życie nic nie jest pomijane")
uwagi = []
core._wybierz_podjednostki_html(art1, core._odnosniki(KEY, HTML), PRZED, uwagi)
sprawdz(len(uwagi) == 1 and "pkt 2a" in uwagi[0], "HTML: dzień wcześniej pkt 2a pominięty")
komunikat = core._odmowa_przyszly({"name": "Ustawa o latarniach"}, "art. 2", "Dz.U. 2099 poz. 1",
                                  "https://example.invalid/t.pdf", PO, True)
sprawdz(komunikat.startswith("❌") and "01.07.2099" in komunikat and "rejestr mgieł" not in komunikat,
        "komunikat: odmowa z datą, bez treści przyszłego przepisu")

print("\nwszystko OK" if not bledy else f"\nbłędów: {bledy}")
sys.exit(1 if bledy else 0)
