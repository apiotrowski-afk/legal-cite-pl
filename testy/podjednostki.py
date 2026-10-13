"""Wybór obowiązującego brzmienia paragrafu/ustępu drukowanego dwa razy — sieć.

Art. 131¹ᵃ § 1 k.p.c. w t.j. Dz.U. 2026 poz. 468: brzmienie do 31.05.2026
i od 1.06.2026 (doręczenia przez portal stronie, która wybrała ten sposób;
pytanie P05 benchmarku). Narzędzie ma zwrócić nowe brzmienie, jedno, z uwagą.

Jednostki dodane, ale jeszcze nieobowiązujące (drukowane raz, z odnośnikiem
„Dodany przez…” i przyszłą datą): art. 94 pkt 2c, art. 104¹ § 1 pkt 10 i art.
94³ᵃ k.p. w t.j. Dz.U. 2026 poz. 1245 wchodzą w życie 5.11.2026; art. 860 § 3
i 4 k.c. — 1.11.2028 (odnośnik podaje dwie daty: ustawy i przepisu). Przed
datą narzędzie nie może ich oddać jako obowiązujących; oczekiwania poniżej
zależą od dnia uruchomienia.

Przy okazji: numery z dwiema literami (59aa) i nagłówki oddziałów doklejane
do artykułu (pr. aut. art. 22).

    python testy/podjednostki.py
"""
import asyncio, datetime, pathlib, sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from legal_cite import core

PRZYPADKI = [
    # (cytat, musi zawierać, nie może zawierać)
    ("art. 131¹ᵃ § 1 k.p.c.", "a także stronie, która dokonała wyboru", "oraz Prokuratorii Generalnej"),
    ("art. 131¹ᵃ k.p.c.", "drukuje 2 brzmienia § 1", "oraz Prokuratorii Generalnej"),
    ("art. 479⁶¹ § 1 KPC", "komunikacji elektronicznej", "telekomunikacji i poczty"),
    ("art. 183 § 1 k.r.o.", "Jeżeli pełnoletnia osoba niepełnosprawna", "Dla osoby niepełnosprawnej ustanawia"),
    ("art. 59aa u.k.k.", "Art. 59aa.", "Nieznany kod aktu"),
    ("art. 43ba KK", "Art. 43ba.", "Nieznany kod aktu"),
    ("art. 7aa u.p.k.", "Art. 7aa.", "Nieznany kod aktu"),
    ("art. 22 PrAut", "(uchylony)", "Oddział"),
    ("art. 35 PrAut", "słuszne interesy twórcy", "Oddział"),
    ("art. 6³ PrAut", "Art. 6", "nie przeszedł kontroli"),
    ("art. 2 u.p.k.", "Art. 2.", "nie przeszedł kontroli"),
]
DZIS = datetime.date.today()
# (cytat, dzień wejścia w życie, fragment dodanej jednostki)
DODANE = [
    ("art. 94 k.p.", datetime.date(2026, 11, 5), "przeciwdziałać naruszaniu godności oraz innych dóbr osobistych"),
    ("art. 104¹ k.p.", datetime.date(2026, 11, 5), "reguły, procedury oraz częstotliwość działań"),
    ("art. 860 KC", datetime.date(2028, 11, 1), "z wykorzystaniem wzoru umowy"),
    ("art. 125¹ k.p.c.", datetime.date(2027, 3, 1), "zgłoszenie się do udziału w sprawie"),
]
# całe artykuły dodane: przed datą odmowa z informacją, bez treści
DODANE_ART = [
    ("art. 94³ᵃ k.p.", datetime.date(2026, 11, 5), "ustala reguły, procedury"),
    ("art. 18³ᶠ k.p.", datetime.date(2026, 11, 5), "uprawdopodobnienia naruszenia"),
]


async def main():
    bledy = 0
    for cyt, jest, nie in PRZYPADKI:
        r = await core.verify_article(cyt)
        ok = jest in r and nie not in r and not r.startswith("❌")
        bledy += not ok
        print("ok " if ok else "ZLE", cyt, "" if ok else "| " + r[:300].replace("\n", " "))
    for cyt, data, fragment in DODANE:
        r = await core.verify_article(cyt)
        if DZIS < data:
            ok = (not r.startswith("❌") and fragment not in r and "Pominięto" in r
                  and f"{data:%d.%m.%Y}" in r)
        else:
            ok = not r.startswith("❌") and fragment in r and "Pominięto" not in r
        bledy += not ok
        print("ok " if ok else "ZLE", cyt, f"(dodana jednostka od {data})",
              "" if ok else "| " + r[:300].replace("\n", " "))
    for cyt, data, fragment in DODANE_ART:
        r = await core.verify_article(cyt)
        if DZIS < data:
            ok = (r.startswith("❌") and "jeszcze nie obowiązuje" in r and fragment not in r
                  and f"{data:%d.%m.%Y}" in r)
        else:
            ok = not r.startswith("❌") and fragment in r
        bledy += not ok
        print("ok " if ok else "ZLE", cyt, f"(artykuł dodany od {data})",
              "" if ok else "| " + r[:300].replace("\n", " "))
    razem = len(PRZYPADKI) + len(DODANE) + len(DODANE_ART)
    print(f"\n{razem - bledy}/{razem} OK")
    sys.exit(1 if bledy else 0)


asyncio.run(main())
