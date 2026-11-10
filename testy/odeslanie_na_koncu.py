"""Ustęp kończący się odesłaniem („… oraz art. 124.”, „… w ust. 3.”) — bez sieci (#14).

Kropka skrótu „art.”/„ust.”/„poz.” nie kończy zdania, więc numer po niej nie
jest nową jednostką. Przypadki z treści #14 i ze stres-testu z Astrą (2026-11-09).

    python testy/odeslanie_na_koncu.py
"""
import pathlib, sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from legal_cite.core import _cut_ustep

bledy = 0


def sprawdz(tekst, ustep, oczekiwane):
    global bledy
    wynik = _cut_ustep(tekst, ustep)
    ok = wynik == oczekiwane
    bledy += not ok
    print("ok " if ok else "ZLE", f"ust. {ustep}: {wynik!r}" + ("" if ok else f" (oczekiwane {oczekiwane!r})"))


# #14: art. 86 ust. 1 VAT — koniec ustępu nie może zgubić „124.”
sprawdz("Art. 86. 1. W zakresie… z zastrzeżeniem art. 114, art. 119 ust. 4, art. 120 ust. 17 i 19 "
        "oraz art. 124. 2. Kwotą podatku naliczonego jest…", "1",
        "1. W zakresie… z zastrzeżeniem art. 114, art. 119 ust. 4, art. 120 ust. 17 i 19 oraz art. 124.")
# minimalny przypadek z #14
sprawdz("Art. 5. 1. Stosuje się przepis ust. 3. 2. Dalej.", "1", "1. Stosuje się przepis ust. 3.")
# art. 5 ust. 3 u.m.w.p.: „ust. 3.” na końcu ust. 2 nie jest początkiem ust. 3 (zwracane było samo „3.”)
U = ("Art. 5. 1. Wysokość… z zastrzeżeniem ust. 4. 2. Jeżeli… wskaźnikiem weryfikacyjnym, o którym mowa w ust. 3. "
     "3. Wskaźnik weryfikacyjny otrzymuje się… o której mowa w art. 2 ust. 2 pkt 1. 4. Jeżeli w roku…")
sprawdz(U, "3", "3. Wskaźnik weryfikacyjny otrzymuje się… o której mowa w art. 2 ust. 2 pkt 1.")
sprawdz(U, "2", "2. Jeżeli… wskaźnikiem weryfikacyjnym, o którym mowa w ust. 3.")
# odesłanie „Art.” wielką literą i do pozycji Dz.U.
sprawdz("Art. 7. 1. Jak w Art. 12. 2. Ogłasza się w Dz. U. z 2020 r. poz. 5. 3. Koniec.", "2",
         "2. Ogłasza się w Dz. U. z 2020 r. poz. 5.")
# bez regresji: nagłówek „Art. 1. 1.”, data „r.” przed kolejnym §, ustęp z literą
sprawdz("Art. 1. 1. Nabycie. 2. Dalej.", "1", "1. Nabycie.")
sprawdz("Art. 2. § 1. Coś od 1 stycznia 2020 r. § 2. Inne.", "1", "§ 1. Coś od 1 stycznia 2020 r.")
sprawdz("Art. 3. 1. A w art. 5. 1a. B. 2. C.", "1", "1. A w art. 5.")
sprawdz("Art. 3. 1. A w art. 5. 1a. B. 2. C.", "1a", "1a. B.")

print("BŁĘDÓW:", bledy)
sys.exit(1 if bledy else 0)
