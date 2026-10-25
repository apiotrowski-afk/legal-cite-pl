"""Brzmienie na dzień — przypadki ze znaną odpowiedzią (wymaga sieci, kilka minut).

Każdy przypadek: cytat, dzień, słowa, które MUSZĄ być w treści, słowa, których
NIE MOŻE być, i dopuszczalne ustalenia. Zmiany prawa użyte w testach:
- art. 118 k.c.: 10 lat → 6 lat + koniec roku od 9.07.2018 (Dz.U. 2018 poz. 1104);
- art. 117¹ k.c.: dodany od 9.07.2018;
- art. 36 § 1 k.p.: od 22.02.2016 także umowy na czas określony (Dz.U. 2015 poz. 1220);
- art. 148 § 1 k.k.: od 1.10.2023 „od lat 10” zamiast „od lat 8”;
- ustawa o prawach konsumenta: w życie od 25.12.2014;
- art. 12–15 u.ś.u.d.e.: uchylone od 6.11.2026 (Dz.U. 2026 poz. 1296).

    python testy/na_dzien.py
"""
import asyncio
import pathlib
import re
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from legal_cite import na_dzien  # noqa: E402

DZIS = __import__("datetime").date.today().isoformat()
POTW = ("potwierdzone_brak_nowelizacji", "potwierdzone_identyczne_w_kolejnym_tj",
        "potwierdzone_kolejny_tj", "potwierdzone_brzmieniem_z_nowelizacji", "potwierdzone_brak_artykulu")
USTAL = POTW + ("ustalone_z_tresci_nowelizacji",)
# (cytat, dzień, musi zawierać, nie może zawierać, dopuszczalne ustalenia; None = odmowa „❌”)
PRZYPADKI = [
    ("art. 118 KC", "2018-07-08", ["lat dziesięć"], ["sześć lat"], POTW),
    ("art. 118 KC", "2018-07-09", ["sześć lat", "ostatni dzień roku"], ["lat dziesięć"], USTAL),
    ("art. 118 KC", "2018-07-10", ["sześć lat"], ["lat dziesięć"], USTAL),
    ("art. 118 KC", "2015-01-01", ["lat dziesięć"], ["sześć lat"], USTAL),
    ("art. 118 KC", "2020-01-01", ["sześć lat"], ["lat dziesięć"], POTW),
    ("art. 117¹ KC", "2018-01-01", ["nie istniał"], ["konsument"], USTAL),
    # #11: indeks z literą — wcześniej ścieżka zapasowa oddawała art. 131 („operatora pocztowego”)
    ("art. 131¹ᵃ k.p.c.", "2021-01-01", ["nie istniał"], ["operatora pocztowego"], USTAL),
    ("art. 131[1a] § 1 KPC", "2024-10-01", ["niemożności doręczenia"], ["operatora pocztowego"], USTAL),
    ("art. 117¹ KC", "2019-01-01", ["konsument"], ["nie istniał"], USTAL),
    ("art. 646 KC", "2020-01-01", ["lat dwóch"], [], POTW),
    ("art. 36 § 1 KP", "2015-06-01", ["czas nieokreślony jest uzależniony"], ["zawartej na czas określony jest"], USTAL),
    ("art. 36 § 1 KP", "2016-03-01", ["umowy o pracę zawartej na czas określony"], [], USTAL),
    ("art. 22 § 1¹ KP", "2020-01-01", ["podaję cały artykuł", "bez względu na nazwę"], [], USTAL),
    ("art. 154 § 1 KSH", "2020-01-01", ["5000 złotych"], ["50 000"], USTAL),
    ("art. 148 § 1 KK", "2022-01-01", ["od lat 8"], ["od lat 10"], USTAL),
    ("art. 148 § 1 KK", "2024-01-01", ["od lat 10"], ["od lat 8"], USTAL),
    ("art. 27 u.p.k.", "2014-06-01", ["jeszcze nie obowiązywała"], [], None),
    ("art. 14 u.ś.u.d.e.", "2026-11-20", ["Dz.U. 2026 poz. 1296", "06.11.2026", "nie obowiązuje"], [],
     ("ustalone_uchylony",)),
    ("art. 15 u.ś.u.d.e.", "2026-12-01", ["UCHYLA art. 15"], [], ("ustalone_uchylony",)),
    ("art. 2 u.ś.u.d.e.", "2026-12-01", ["Dz.U. 2026 poz. 1296"], ["UCHYLA art. 2"], USTAL + ("nieustalone",)),
    ("art. 6 RODO", "2020-01-01", ["tylko dla aktów polskich"], [], None),
    ("art. 118 KC", "2018-13-45", ["Nierozpoznana data"], [], None),
    # bez znanej odpowiedzi — sprawdzamy, że narzędzie nie udaje pewności
    ("art. 385¹ § 1 KC", "2010-01-01", ["niedozwolone postanowienia"], [], USTAL + ("nieustalone",)),
    ("art. 148 § 1 KK", DZIS, ["od lat 10"], [], USTAL + ("nieustalone",)),
    ("art. 70 § 1 O.p.", "2020-01-01", ["5 lat"], [], USTAL + ("nieustalone",)),
    ("art. 118 KC", "2028-12-01", ["sześć lat"], [], USTAL + ("nieustalone",)),
]
if DZIS < "2026-11-06":  # zapowiedziane uchylenie widać tylko przed jego datą
    PRZYPADKI.append(("art. 14 u.ś.u.d.e.", DZIS, ["uchyla art. 14 z dniem 06.11.2026", "Nie ponosi odpowiedzialności"],
                      [], USTAL + ("nieustalone",)))


def ustalenie(tekst: str) -> str | None:
    m = re.search(r"ustalenie=(\w+)", tekst)
    return m.group(1) if m else None


async def main() -> int:
    bledy = 0
    for cytat, dzien, musi, nie_moze, ustalenia in PRZYPADKI:
        t0 = time.monotonic()
        tekst = await na_dzien.verify_article_na_dzien(cytat, dzien)
        sek = time.monotonic() - t0
        tresc = tekst.split("[dla modelu]")[0]
        kod = ustalenie(tekst)
        problemy = [f"brak „{s}”" for s in musi if s not in tresc]
        problemy += [f"jest „{s}”" for s in nie_moze if s in tresc.split("Nowelizacje ustawy")[0]
                     .split("Brzmienie w kolejnym tekście")[0]]
        if ustalenia is None:
            if not tekst.startswith("❌"):
                problemy.append("oczekiwano odmowy")
        elif kod not in ustalenia:
            problemy.append(f"ustalenie {kod}")
        bledy += bool(problemy)
        print(f"{'OK  ' if not problemy else 'BŁĄD'} {cytat:20} {dzien}  {kod or tekst[:60]!s:42} {sek:5.1f}s "
              + ("; ".join(problemy)), flush=True)
    print(f"\n{len(PRZYPADKI) - bledy}/{len(PRZYPADKI)} zgodnych")
    return 1 if bledy else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
