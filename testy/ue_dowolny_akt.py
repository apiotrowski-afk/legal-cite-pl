"""Dowolny akt UE po numerze, CELEX-ie albo nazwie traktatu — sieć.

Dotąd akt UE dało się zacytować tylko jednym z kilku kodów (RODO, DSA, AI Act…).
Narzędzie ma rozpoznać rodzaj i numer aktu w obu porządkach numeracji
(rozporządzenia do 2014 r. numer/rok, od 2015 r. rok/numer; dyrektywy rok/numer),
potwierdzić kandydata tytułem z CELLAR i odmówić, gdy aktu nie ma albo nie obowiązuje.
Przy okazji: ust. 1 zaraz po numerze artykułu („Artykuł 6 1. …”) i nagłówek
traktatu „(dawny artykuł 81 TWE)”, który nie może być granicą artykułu.

    python testy/ue_dowolny_akt.py
"""
import asyncio, pathlib, sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from legal_cite import core

PRZYPADKI = [
    # (cytat, musi zawierać, nie może zawierać)
    ("art. 6 ust. 1 dyrektywy 93/13/EWG", "nieuczciwe warunki w umowach zawieranych przez sprzedawców", "2. Państwa"),
    ("art. 3 ust. 1 dyrektywy Rady 93/13/EWG", "Dyrektywa Rady 93/13/EWG", "▼"),
    ("art. 4 ust. 1 rozporządzenia (WE) nr 593/2008", "umowa sprzedaży towarów podlega prawu", "2. "),
    ("art. 25 rozporządzenia (UE) nr 1215/2012", "(UE) nr 1215/2012", "Artykuł 26"),
    ("art. 5 rozporządzenia 2016/679", "Zasady dotyczące przetwarzania danych osobowych", "Artykuł 6"),
    ("art. 1 CELEX 32019L0770", "(UE) 2019/770", "Nieznany"),
    ("art. 101 TFUE", "Niezgodne z rynkiem wewnętrznym", "Artykuł 102"),
    ("art. 81 TFUE", "współpracę sądową w sprawach cywilnych", "porozumienia między przedsiębiorstwami"),
    ("art. 4 ust. 3 TUE", "zasadą lojalnej współpracy", "Artykuł 5"),
    ("art. 47 Karty praw podstawowych", "skutecznego środka prawnego", "Artykuł 48"),
    ("art. 2 decyzji 2011/753/UE", "Decyzja Komisji z dnia 18 listopada 2011", "2011/753/UE: "),
    # stary tytuł bez numeru („Dyrektywa Rady z dnia 25 lipca 1985 r. …”), tekst z wydania specjalnego
    ("art. 1 dyrektywy 85/374/EWG", "Producent jest odpowiedzialny za szkodę", "Artykuł 2"),
    ("art. 1 dyrektywy 88/506/EWG", "Dyrektywa Komisji z dnia 13 września 1988", "Nie znalazłem"),
    ("art. 1 CELEX 31992R0597", "Nomenklaturze Scalonej", "Nie udało się pobrać"),
    # odmowy
    ("art. 1 dyrektywy 85/375/EWG", "Nie znalazłem w CELLAR", "Artykuł 1"),
    ("art. 3 dyrektywy 95/46/WE", "nie obowiązuje", "Artykuł 3"),
    ("art. 1 dyrektywy 2099/1", "Nie znalazłem w CELLAR", "Artykuł 1"),
    # słownik kodów bez zmian
    ("art. 28 ust. 3 RODO", "Rozporządzenie 2016/679 (RODO/GDPR)", "Artykuł 28"),
]


async def main():
    bledy = 0
    for cyt, jest, nie in PRZYPADKI:
        r = await core.verify_article(cyt)
        odmowa = jest.startswith(("nie obowiązuje", "Nie znalazłem"))
        ok = jest in r and nie not in r and (r.startswith("❌") == odmowa)
        bledy += not ok
        print(("OK  " if ok else "BŁĄD"), cyt, "" if ok else "\n     " + r[:300].replace("\n", " | "))
    print(f"{len(PRZYPADKI) - bledy}/{len(PRZYPADKI)} OK")
    sys.exit(1 if bledy else 0)


asyncio.run(main())
