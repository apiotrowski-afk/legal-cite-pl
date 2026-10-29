"""Brzmienie aktu UE na wskazany dzień — sieć.

Wersja skonsolidowana obowiązująca w danym dniu (najnowsza z datą nie późniejszą),
także dla aktu już uchylonego, jeśli wtedy obowiązywał; odmowa przed wejściem
w życie i po utracie mocy.

    python testy/ue_na_dzien.py
"""
import asyncio, pathlib, sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from legal_cite import na_dzien as nd

PRZYPADKI = [
    # (cytat, dzień, musi zawierać, nie może zawierać, odmowa)
    ("art. 111 ust. 4 AI Act", "2026-09-01", "do dnia 2 grudnia 2026", "tekst pierwotny", False),
    ("art. 111 ust. 4 AI Act", "2026-01-01", "nie znaleziony", "Dostawcy systemów AI", True),   # ust. 4 dodany w 2026
    ("art. 3 dyrektywy 95/46/WE", "2010-01-01", "Niniejsza dyrektywa stosuje się", "nie obowiązuje", False),
    ("art. 3 dyrektywy 95/46/WE", "2019-01-01", "już nie obowiązywał", "Artykuł 3", True),
    ("art. 4 dyrektywy 87/102/EWG", "2005-06-01", "Umowy kredytu zawierane są na piśmie", "Nie znalazłem", False),
    ("art. 5 RODO", "2015-01-01", "jeszcze nie obowiązywał", "Artykuł 5", True),
    ("art. 10 dyrektywy 2008/48/WE", "2012-01-01", "02008L0048-2011", "Nie znalazłem", False),
    ("art. 101 TFUE", "2020-01-01", "02016E/TXT-2019", "Artykuł 102", False),
]


async def main():
    bledy = 0
    for cyt, d, jest, nie, odmowa in PRZYPADKI:
        r = await nd.verify_article_na_dzien(cyt, d)
        ok = jest in r and nie not in r and r.startswith("❌") == odmowa
        bledy += not ok
        print(("OK  " if ok else "BŁĄD"), cyt, d, "" if ok else "\n     " + r[:300].replace("\n", " | "))
    print(f"{len(PRZYPADKI) - bledy}/{len(PRZYPADKI)} OK")
    sys.exit(1 if bledy else 0)


asyncio.run(main())
