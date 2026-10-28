"""Zdanie wydrukowane w dwóch brzmieniach — bez sieci (#13).

Art. 505 k.p.k. (t.j. Dz.U. 2026 poz. 490) drukuje po dwa brzmienia trzech zdań
jedno po drugim: „Odpis wyroku…” (odnośnik 5: obowiązuje do wejścia w życie
zmiany z odnośnika 6) i „Kopię wyroku…” (od 1.10.2029). Wybór brzmienia działa
na jednostkach, nie na zdaniach, więc narzędzie oddawało oba zdania sklejone.
Od 28.10.2026: gdy nowe brzmienie jeszcze nie obowiązuje, jest wycinane (od
odnośnika A do B); gdy już obowiązuje — jednostka niejednoznaczna (odmowa),
bo początku starego zdania nie da się pewnie wyznaczyć.

    python testy/zdania_dwa_brzmienia.py
"""
import pathlib, sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from legal_cite import core

bledy = 0


def sprawdz(ok: bool, opis: str) -> None:
    global bledy
    bledy += not ok
    print("ok " if ok else "ZLE", opis)


MAPA = {
    "5": "Zdanie pierwsze w tym brzmieniu obowiązuje do wejścia w życie zmiany, o której mowa w odnośniku 6.",
    "6": "Zdanie pierwsze ze zmianą wprowadzoną przez art. 82 pkt 1 ustawy z dnia 18 listopada 2020 r. "
         "o doręczeniach elektronicznych (Dz. U. poz. 2320), która wejdzie w życie z dniem 1 października 2029 r.",
    "7": "Dodany przez art. 1 pkt 3 ustawy z dnia 5 maja 2025 r. (Dz. U. poz. 600), która weszła w życie "
         "z dniem 1 czerwca 2025 r.",
    "9": "§ 2 w tym brzmieniu obowiązuje do wejścia w życie zmiany, o której mowa w odnośniku 10.",
}
u = core._zdania_dwa_brzmienia(MAPA, ["5", "6", "5"])
sprawdz(len(u) == 1 and "zdanie pierwsze" in u[0] and "odnośniki 5 i 6" in u[0] and "01.10.2029" in u[0],
        f"zdanie w dwóch brzmieniach rozpoznane, z datą: {u}")
sprawdz(core._zdania_dwa_brzmienia(MAPA, ["6", "7"]) == [], "zwykłe odnośniki nie są brane za zdania")
sprawdz(core._zdania_dwa_brzmienia(MAPA, ["9"]) == [],
        "odnośnik paragrafu („§ 2 w tym brzmieniu…”) zostaje dla wyboru brzmień jednostek")

import datetime
from legal_cite import pdf_tj

MD = ("Odpis wyroku doręcza się oskarżycielowi – wraz z odpisem aktu oskarżenia.[^5] "
      "Kopię wyroku doręcza się oskarżycielowi – wraz z kopią aktu oskarżenia.[^6] "
      "W każdym wypadku odpis doręcza się prokuratorowi.")
for dzis, jest, nie, rozstrz in [
        (datetime.date(2026, 10, 28), "odpisem aktu oskarżenia. W każdym", "Kopię", True),
        (datetime.date(2030, 1, 1), "Kopię", "", False)]:
    wyb = {"przypisy": MAPA, "dzis": dzis, "uwagi": [], "niejednoznaczne": False, "zdania_ok": set()}
    t = pdf_tj._PRZYPIS_RE.sub("", pdf_tj._wybierz_zdania(MD, wyb))
    ok = jest in t and (not nie or nie not in t) and (("5" in wyb["zdania_ok"]) == rozstrz)
    sprawdz(ok, f"PDF na {dzis}: {'wycięte nowe brzmienie' if rozstrz else 'para zostaje (odmowa)'}: {t[:70]!r}")

A = lambda n: f'<a class="gloss-link" href="#"><sup>{n})</sup></a>'
HTML = (f"<p>Odpis wyroku doręcza się – wraz z odpisem aktu oskarżenia.{A(5)} "
        f"Kopię wyroku doręcza się – wraz z kopią aktu oskarżenia.{A(6)} W każdym wypadku…</p>")
uw = []
frag, ok_ = core._wybierz_zdania_html(HTML, MAPA, datetime.date(2026, 10, 28), uw)
sprawdz("Kopię" not in frag and "W każdym wypadku" in frag and ok_ == {"5"} and "01.10.2029" in uw[0],
        "HTML: nowe brzmienie wycięte, uwaga z datą")
frag, ok_ = core._wybierz_zdania_html(HTML, MAPA, datetime.date(2030, 1, 1), [])
sprawdz("Kopię" in frag and not ok_, "HTML po dacie nowego brzmienia: bez zmian (odmowa wyżej)")

print("wszystko OK" if not bledy else f"{bledy} błędów")
sys.exit(1 if bledy else 0)
