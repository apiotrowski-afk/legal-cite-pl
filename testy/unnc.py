"""Ustawa o nabywaniu nieruchomości przez cudzoziemców (u.n.n.c.) — sieć (kilkadziesiąt sekund).

Akt pierwotny Dz.U. 1920 nr 31 poz. 178 (ELI DU/1920/178), t.j. Dz.U. 2017 poz. 2278 (HTML),
nowela Dz.U. 2026 poz. 1099 w życie 19.11.2026 (sprawdzone w API ELI 2026-10-24). Pytanie P04
benchmarku: art. 1 ust. 1 (zezwolenie w drodze decyzji administracyjnej), art. 1 ust. 1a
(sprzeciw w drodze postanowienia, 14 dni), art. 8 (wyjątki od zezwolenia).

Przy okazji: tekst jednolity drukuje „Art. 1. 1. Nabycie…” — nagłówek artykułu nie jest
ustępem 1, więc „art. 1 ust. 1” nie może oddać samego „1.” (poprawka w _cut_ustep).

    python testy/unnc.py
"""
import asyncio
import datetime
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from legal_cite import core  # noqa: E402
from legal_cite.na_dzien import verify_article_na_dzien  # noqa: E402

bledy = 0


def sprawdz(ok: bool, opis: str) -> None:
    global bledy
    bledy += not ok
    print("ok " if ok else "ZLE", opis)


# kody skrótów (bez sieci)
for kod in ("UNNC", "u.n.n.c.", "u.n.n.c", "unnc", "ustawy o nabywaniu nieruchomości przez cudzoziemców"):
    k = core._resolve(kod, core.PL_ACTS)
    sprawdz(k is not None and core.PL_ACTS[k]["year"] == 1920 and core.PL_ACTS[k]["pos"] == 178,
            f"_resolve({kod!r}) → {k} (DU/1920/178)")

# wycinanie ustępu, gdy numer artykułu = numer ustępu (bez sieci)
UST = "Art. 1. 1. Nabycie wymaga zezwolenia. 1a. Sprzeciw w drodze postanowienia. 2. Zezwolenie wydaje minister."
sprawdz(core._cut_ustep(UST, "1") == "1. Nabycie wymaga zezwolenia.", f"ust. 1 przy „Art. 1. 1.”: {core._cut_ustep(UST, '1')!r}")
sprawdz(core._cut_ustep(UST, "1a") == "1a. Sprzeciw w drodze postanowienia.", f"ust. 1a: {core._cut_ustep(UST, '1a')!r}")
sprawdz(core._cut_ustep(UST, "2") == "2. Zezwolenie wydaje minister.", f"ust. 2: {core._cut_ustep(UST, '2')!r}")
sprawdz(core._cut_ustep("Art. 10. 1. A. 2. B.", "1") == "1. A.", "ust. 1 przy „Art. 10. 1.” bez zmian")

# treść z oficjalnego źródła (sieć)
PRZYPADKI = [
    # (cytat, musi zawierać, nie może zawierać)
    ("art. 1 ust. 1 UNNC", ["Nabycie nieruchomości przez cudzoziemca wymaga zezwolenia", "w drodze decyzji administracyjnej"],
     ["w drodze postanowienia"]),
    ("art. 1 ust. 1a u.n.n.c.", ["w drodze postanowienia", "14 dni"], ["decyzji administracyjnej"]),
    ("art. 8 UNNC", ["Art. 8.", "Nie wymaga uzyskania zezwolenia"], []),
    ("art. 8 ust. 2 ustawy o nabywaniu nieruchomości przez cudzoziemców", ["Europejskim Obszarze Gospodarczym"], ["Art. 8. 1."]),
]
for cyt, musi, nie_moze in PRZYPADKI:
    out = asyncio.run(core.verify_article(cyt))
    sprawdz(out.startswith("📜") and "DU/2017/2278" in out, f"{cyt}: tekst urzędowy HTML z t.j. DU/2017/2278")
    for s in musi:
        sprawdz(s in out, f"{cyt}: zawiera „{s}”")
    for s in nie_moze:
        sprawdz(s not in out, f"{cyt}: nie zawiera „{s}”")

# nowela Dz.U. 2026 poz. 1099 (w życie 19.11.2026): przed tym dniem „oczekuje”, od tego dnia — nowelizacja po t.j.
out = asyncio.run(core.verify_article("art. 8 UNNC"))
if datetime.date.today() < datetime.date(2026, 11, 19):
    sprawdz("nowelizacje_oczekujace=DU/2026/1099@2026-11-19" in out and "nowelizacje_po_tj=brak" in out,
            "nowela 2026/1099 oczekująca (jeszcze nie obowiązuje), brak nowelizacji po t.j.")
else:
    sprawdz("DU/2026/1099" in out.split("nowelizacje_po_tj=")[-1].split(";")[0],
            "nowela 2026/1099 wśród nowelizacji po t.j. (weszła w życie 19.11.2026)")

# brzmienie na dzień (data stanu prawnego P04)
nd = asyncio.run(verify_article_na_dzien("art. 1 ust. 1 UNNC", "2026-10-01"))
sprawdz(nd.startswith("📜") and "w drodze decyzji administracyjnej" in nd and "potwierdzone" in nd,
        "na dzień 2026-10-01: art. 1 potwierdzony, z treścią ust. 1")

# nieistniejący artykuł → odmowa
sprawdz(asyncio.run(core.verify_article("art. 99 UNNC")).startswith("❌"), "art. 99 UNNC → ❌ (nie znaleziony)")

print("wszystko OK" if not bledy else f"{bledy} błędów")
sys.exit(1 if bledy else 0)
