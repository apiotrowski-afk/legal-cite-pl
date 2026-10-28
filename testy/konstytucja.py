"""Konstytucja z tekstu ujednoliconego Kancelarii Sejmu (ELI, plik typu „U”) — sieć.

Tekstu jednolitego Konstytucji w Dz.U. nie ma, a PDF pierwotny z 1997 r. nie
zawiera zmian z 2006 r. (art. 55 — ekstradycja) i 2009 r. (art. 99 ust. 3).

    python testy/konstytucja.py
"""
import asyncio, pathlib, sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from legal_cite import core, na_dzien

PRZYPADKI = [
    # (cytat, musi zawierać, nie może zawierać)
    ("art. 55 ust. 1 Konstytucji", "z wyjątkiem przypadków określonych w ust. 2 i 3.", "2. Ekstradycja"),
    ("art. 55 ust. 2 Konstytucji RP", "sądowego organu międzynarodowego", "❌"),   # zmiana z 2006 r.
    ("art. 99 ust. 3 Konstytucji", "osoba skazana prawomocnym wyrokiem", "❌"),       # zmiana z 2009 r.
    ("art. 2 Konstytucja", "demokratycznym państwem prawnym", "❌"),
    ("art. 2 Konstytucja", "NIEURZĘDOWY", "tekst urzędowy HTML"),
    ("art. 300 Konstytucji", "nie znaleziony", "Art. 300"),
]


async def main():
    bledy = 0
    for cyt, jest, nie in PRZYPADKI:
        r = await core.verify_article(cyt)
        ok = jest in r and nie not in r
        bledy += not ok
        print("ok " if ok else "ZLE", cyt, "" if ok else "| " + r[:300].replace("\n", " "))
    r = await na_dzien.verify_article_na_dzien("art. 2 Konstytucji", "2005-01-01")
    ok = r.startswith("❌") and "tekst ujednolicony" in r
    bledy += not ok
    print("ok " if ok else "ZLE", "na_dzien dla Konstytucji → jawna odmowa")
    print("wszystko OK" if not bledy else f"{bledy} błędów")
    return bledy


sys.exit(1 if asyncio.run(main()) else 0)
