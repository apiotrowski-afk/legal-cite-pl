"""Uchylenie jednostki artykułu to nie uchylenie artykułu — bez sieci.

„w art. 78 uchyla się § 2” uchyla tylko § 2; „na dzień” podawał wtedy, że cały
art. 78 k.c. nie obowiązuje (test k.c. na dzień 31.12.2016, 2026-11-10).

    python testy/uchylenie_jednostki.py
"""
import pathlib, sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from legal_cite.na_dzien import _uchyla

PRZYPADKI = [
    ("8) w art. 78 uchyla się § 2; 9) po art. 78 dodaje się art. 78 1", "78", False),
    ("w art. 5 uchyla się ust. 3;", "5", False),
    ("w art. 78 uchyla się pkt 2", "78", False),
    ("uchyla się art. 78 § 2;", "78", False),
    ("w art. 10 uchyla się zdanie drugie;", "10", False),
    ("uchyla się art. 78;", "78", True),
    ("5) art. 78 uchyla się;", "78", True),
    ("uchyla się art. 12–15;", "13", True),
    ("art. 781 uchyla się;", "78", False),
]
bledy = 0
for tekst, art, oczek in PRZYPADKI:
    wynik = _uchyla(tekst, art, None)
    bledy += wynik != oczek
    print("ok " if wynik == oczek else "ZLE", f"art. {art}: {tekst!r} → {wynik}")
print(f"\n{len(PRZYPADKI) - bledy}/{len(PRZYPADKI)}")
sys.exit(1 if bledy else 0)
