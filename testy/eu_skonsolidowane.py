"""Akty UE z wersji skonsolidowanej, nie z tekstu pierwotnego — sieć.

AI Act pobierany jako CELEX 32024R1689 (tekst z Dz.U. UE z 12.7.2024) nie
miał art. 111 ust. 4 dodanego rozporządzeniem (UE) 2026/1744, więc
weryfikator przeoczyłby zmianę. Narzędzie ma wziąć najnowszą obowiązującą
wersję skonsolidowaną (0…-RRRRMMDD), oznaczyć ją jako nieurzędową, wskazać
akt zmieniający artykuł i nie przepuścić znaczników ►M1/▼B do cytatu.

    python testy/eu_skonsolidowane.py
"""
import asyncio, pathlib, sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from legal_cite import core

PRZYPADKI = [
    # (cytat, musi zawierać, nie może zawierać)
    ("art. 111 ust. 4 AI Act", "zgodności z art. 50 ust. 2 do dnia 2 grudnia 2026", "▼"),
    ("art. 111 ust. 4 AI Act", "(UE) 2026/1744", "tekst pierwotny"),
    ("art. 111 AIA", "TEKST SKONSOLIDOWANY", "►"),
    ("art. 28 ust. 3 RODO", "C1 = Sprostowanie", "akt zmieniający;"),
    ("art. 3 ust. 1 NIS2", "Do celów niniejszej dyrektywy", "Nieznany kod aktu"),
]


async def main():
    bledy = 0
    for cyt, jest, nie in PRZYPADKI:
        r = await core.verify_article(cyt)
        ok = jest in r and nie not in r and not r.startswith("❌")
        bledy += not ok
        print("ok " if ok else "ZLE", cyt, "" if ok else "| " + r[:300].replace("\n", " "))
    print("wszystko OK" if not bledy else f"{bledy} błędów")
    return bledy


if __name__ == "__main__":
    sys.exit(1 if asyncio.run(main()) else 0)
