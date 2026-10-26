"""Zdanie wydrukowane w dwóch brzmieniach — bez sieci (#13).

Art. 505 k.p.k. (t.j. Dz.U. 2026 poz. 490) drukuje po dwa brzmienia trzech zdań
jedno po drugim: „Odpis wyroku…” (odnośnik 5: obowiązuje do wejścia w życie
zmiany z odnośnika 6) i „Kopię wyroku…” (od 1.10.2029). Wybór brzmienia działa
na jednostkach, nie na zdaniach, więc narzędzie oddawało oba zdania sklejone.
Teraz taka jednostka jest niejednoznaczna (jawna odmowa).

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

print("wszystko OK" if not bledy else f"{bledy} błędów")
sys.exit(1 if bledy else 0)
