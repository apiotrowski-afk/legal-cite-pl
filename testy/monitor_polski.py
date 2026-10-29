"""Akty z Monitora Polskiego i umowy międzynarodowe po adresie — sieć.

Regulamin Sejmu (uchwała, M.P.) czytany ścieżką PDF z kontrolami wierności,
także kodem „Regulaminu Sejmu”. Umowy międzynarodowe (EKPCz, CISG) ELI drukuje
dwujęzycznie w dwóch kolumnach — jawna odmowa z linkiem do PDF.

    python testy/monitor_polski.py
"""
import asyncio, pathlib, sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from legal_cite import core

PRZYPADKI = [
    ("art. 6 ust. 1 M.P. 2022 poz. 990", "Sejm wybiera 20 sekretarzy Sejmu", "2. Kandydatów", False),
    ("art. 6 MP/1992/185", "Regulamin Sejmu", "Art. 6a", False),
    ("art. 7 ust. 1 Regulaminu Sejmu", "Posła obowiązuje obecność", "2. Poseł", False),
    ("art. 6 Dz.U. 1993 nr 61 poz. 284", "dwujęzycznie w dwóch kolumnach", "Artykuł 6", True),
    ("art. 35 Dz.U. 1997 poz. 286", "to konwencja", "Artykuł 35", True),
    ("art. 6 M.P. 2099 poz. 1", "W Monitorze Polskim nie ma pozycji", "Art.", True),
]


async def main():
    bledy = 0
    for cyt, jest, nie, odmowa in PRZYPADKI:
        r = await core.verify_article(cyt)
        tresc = r.split("[dla modelu]")[0]
        ok = jest in tresc and nie not in tresc.split("\n\n", 1)[-1] and r.startswith("❌") == odmowa
        bledy += not ok
        print(("OK  " if ok else "BŁĄD"), cyt, "" if ok else "\n     " + r[:400].replace("\n", " | "))
    print(f"{len(PRZYPADKI) - bledy}/{len(PRZYPADKI)} OK")
    sys.exit(1 if bledy else 0)


asyncio.run(main())
