"""Wybór obowiązującego brzmienia paragrafu/ustępu drukowanego dwa razy — sieć.

Art. 131¹ᵃ § 1 k.p.c. w t.j. Dz.U. 2026 poz. 468: brzmienie do 31.05.2026
i od 1.06.2026 (doręczenia przez portal stronie, która wybrała ten sposób;
pytanie P05 benchmarku). Narzędzie ma zwrócić nowe brzmienie, jedno, z uwagą.

    python testy/podjednostki.py
"""
import asyncio, pathlib, sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from legal_cite import core

PRZYPADKI = [
    # (cytat, musi zawierać, nie może zawierać)
    ("art. 131¹ᵃ § 1 k.p.c.", "a także stronie, która dokonała wyboru", "oraz Prokuratorii Generalnej"),
    ("art. 131¹ᵃ k.p.c.", "drukuje 2 brzmienia § 1", "oraz Prokuratorii Generalnej"),
    ("art. 479⁶¹ § 1 KPC", "komunikacji elektronicznej", "telekomunikacji i poczty"),
    ("art. 183 § 1 k.r.o.", "Jeżeli pełnoletnia osoba niepełnosprawna", "Dla osoby niepełnosprawnej ustanawia"),
]


async def main():
    bledy = 0
    for cyt, jest, nie in PRZYPADKI:
        r = await core.verify_article(cyt)
        ok = jest in r and nie not in r and not r.startswith("❌")
        bledy += not ok
        print("ok " if ok else "ZLE", cyt, "" if ok else "| " + r[:300].replace("\n", " "))
    print(f"\n{len(PRZYPADKI) - bledy}/{len(PRZYPADKI)} OK")
    sys.exit(1 if bledy else 0)


asyncio.run(main())
