"""Nowelizacje po t.j.: obowiązujące i oczekujące osobno — bez sieci.

Wykaz „Akty zmieniające” w ELI podaje przy k.c. Dz.U. 2026 poz. 507 z datą
1.11.2028. Narzędzie liczyło każdy akt z datą po dacie t.j., bez porównania
z dniem dzisiejszym, i przy każdym artykule k.c. pisało „po dacie tego t.j.
weszła w życie 1 nowelizacja” (zgłoszenie: porównanie z Lex Machina,
16.10.2026). Licznik zastąpiony listą z numerami Dz.U. i datami.

    python testy/nowelizacje.py
"""
import datetime, pathlib, sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from legal_cite import core

bledy = 0


def sprawdz(ok: bool, opis: str) -> None:
    global bledy
    bledy += not ok
    print("ok " if ok else "ZLE", opis)


DZIS = datetime.date(2026, 10, 21)
KC = [{"id": "DU/2025/1508", "date": "2025-12-04"},
      {"id": "DU/2026/184", "date": "2026-05-19"},
      {"id": "DU/2026/507", "date": "2028-11-01"}]

weszle, oczek = core._nowelizacje_po(KC, "2026-05-27", DZIS)
sprawdz(weszle == [], "k.c.: po t.j. z 27.05.2026 nic nie weszło w życie")
sprawdz(oczek == [("DU/2026/507", "2028-11-01")], "k.c.: poz. 507 oczekuje")

weszle, oczek = core._nowelizacje_po(KC, "2025-11-30", DZIS)
sprawdz(weszle == [("DU/2025/1508", "2025-12-04"), ("DU/2026/184", "2026-05-19")],
        "starszy t.j.: dwie weszły, posortowane po dacie")
sprawdz(core._nowelizacje_po(KC, "", DZIS) == ([], []), "bez daty t.j. — puste listy")

# linia aktualności i pola dla modelu (dziś = data uruchomienia, więc daty z przeszłości/przyszłości odległe)
zm = [{"id": "DU/2020/1", "date": "2020-01-01"}, {"id": "DU/2020/2", "date": "2020-02-01"},
      {"id": "DU/2099/9", "date": "2099-01-01"}]
tekst, kod, pola = core._aktualnosc_pl(zm, "2019-12-31")
sprawdz("weszły w życie 2 nowelizacje: Dz.U. 2020 poz. 1 (01.01.2020), Dz.U. 2020 poz. 2 (01.02.2020)"
        in tekst, f"lista z numerami i odmianą: {tekst[:120]}")
sprawdz("Oczekuje" in tekst and "Dz.U. 2099 poz. 9 (01.01.2099)" in tekst, "oczekująca osobno")
sprawdz(kod == "nieustalona_2_nowelizacji_po_tj", f"kod: {kod}")
sprawdz("nowelizacje_po_tj=DU/2020/1@2020-01-01,DU/2020/2@2020-02-01" in pola
        and "nowelizacje_oczekujace=DU/2099/9@2099-01-01" in pola, "pola dla modelu")
tekst, kod, _ = core._aktualnosc_pl(zm[2:], "2019-12-31")
sprawdz(kod == "potwierdzona_wg_wykazu_eli" and "nie weszła w życie żadna" in tekst,
        "tylko przyszła nowelizacja — aktualność potwierdzona, nie „weszła”")
tekst, _, _ = core._aktualnosc_pl(zm[:1], "2019-12-31")
sprawdz("weszła w życie 1 nowelizacja:" in tekst, "odmiana dla 1")

print("wszystko OK" if not bledy else f"{bledy} błędów")
sys.exit(1 if bledy else 0)
