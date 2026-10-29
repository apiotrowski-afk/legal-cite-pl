"""Rozporządzenie po tytule (wyszukiwarka ELI) — sieć.

Część 1: przypadki stałe. Część 2 (--proba N): losowa próba obowiązujących
rozporządzeń (nie zmieniających); pełny tytuł z ELI ma prowadzić z powrotem do
tego samego aktu, a bez daty — do niego albo do jawnej odmowy z kandydatami.
Nigdy do innego aktu.

    python testy/rozporzadzenie_tytul.py [--proba 100] [--seed 2026]
"""
import argparse, asyncio, pathlib, random, re, sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import httpx
from legal_cite import core

ADW = "rozporządzenia Ministra Sprawiedliwości z dnia 22 października 2015 r. w sprawie opłat za czynności adwokackie"
PRZYPADKI = [
    (f"§ 2 {ADW}", "Stawki minimalne wynoszą przy wartości przedmiotu sprawy", False),
    ("§ 2 rozporządzenia w sprawie opłat za czynności adwokackie", "z dnia 22 października 2015 r.", False),
    ("§ 2 rozporządzenia Ministra Sprawiedliwości w sprawie opłat za czynności radców prawnych",
     "czynności radców prawnych**", False),
    # organ albo data niezgodne z tytułem, przedmiot nieistniejący, akt uchylony
    ("§ 2 rozporządzenia Ministra Zdrowia z dnia 22 października 2015 r. w sprawie opłat za czynności adwokackie",
     "Nie znalazłem w ELI rozporządzenia", True),
    ("§ 2 rozporządzenia Ministra Sprawiedliwości z dnia 23 października 2015 r. w sprawie opłat za czynności adwokackie",
     "Nie znalazłem w ELI rozporządzenia", True),
    ("§ 1 rozporządzenia w sprawie czegoś, czego nie ma", "Nie znalazłem w ELI rozporządzenia", True),
    ("§ 1 rozporządzenia Ministra Sprawiedliwości z dnia 28 września 2002 r. w sprawie opłat za czynności "
     "adwokackie oraz ponoszenia przez Skarb Państwa kosztów nieopłaconej pomocy prawnej udzielonej z urzędu",
     "nie obowiązuje", True),
]


async def stale() -> int:
    bledy = 0
    for cyt, jest, odmowa in PRZYPADKI:
        r = await core.verify_article(cyt)
        ok = jest in r and r.startswith("❌") == odmowa
        bledy += not ok
        print(("OK  " if ok else "BŁĄD"), cyt[:100], "" if ok else "\n     " + r[:300].replace("\n", " | "))
    print(f"przypadki stałe: {len(PRZYPADKI) - bledy}/{len(PRZYPADKI)} OK")
    return bledy


async def proba(n: int, seed: int) -> int:
    items, off = [], 0
    async with httpx.AsyncClient(timeout=120, headers=core._HEADERS) as c:
        while True:
            r = await c.get("https://api.sejm.gov.pl/eli/acts/search", params={
                "publisher": "DU", "type": "Rozporządzenie", "inForce": "1", "limit": 500, "offset": off})
            r.raise_for_status()
            it = r.json().get("items", [])
            items += [x for x in it if x.get("status") in ("obowiązujący", "akt posiada tekst jednolity")
                      and " w sprawie " in (x.get("title") or "")
                      and not re.search(r'zmieniające|zmieniajace', x.get("title") or "")]
            if len(it) < 500:
                break
            off += 500
    wybrane = random.Random(seed).sample(items, min(n, len(items)))
    licz = {"z_data_ok": 0, "z_data_inny": 0, "z_data_odmowa": 0, "bez_daty_ok": 0, "bez_daty_odmowa": 0, "bez_daty_inny": 0}
    for x in wybrane:
        tyt = re.sub(r'\s+', ' ', x["title"]).strip().rstrip('.')
        pelny = "rozporządzenia" + tyt[len("Rozporządzenie"):]
        bez = re.sub(r'\s+z dnia \d{1,2} \S+ \d{4} r\.', '', pelny)
        for etykieta, cyt in (("z_data", pelny), ("bez_daty", bez)):
            core._rozporzadzenia.clear()
            w = await core._rozporzadzenie_z_tytulu(cyt)
            if isinstance(w, dict) and (w["year"], w["pos"]) == (x["year"], x["pos"]):
                licz[f"{etykieta}_ok"] += 1
            elif isinstance(w, dict):
                licz[f"{etykieta}_inny"] += 1
                print(f"  INNY AKT {etykieta}: DU/{x['year']}/{x['pos']} → DU/{w['year']}/{w['pos']} | {tyt[:110]}")
            else:
                licz[f"{etykieta}_odmowa"] += 1
                if etykieta == "z_data":
                    print(f"  odmowa z datą: DU/{x['year']}/{x['pos']} | {tyt[:90]} | {str(w)[:120]}")
    print(f"obowiązujące rozporządzenia (bez zmieniających): {len(items)}; próba {len(wybrane)} (seed {seed})")
    print(licz)
    return licz["z_data_inny"] + licz["bez_daty_inny"]


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--proba", type=int, default=0)
    ap.add_argument("--seed", type=int, default=2026)
    a = ap.parse_args()
    bledy = await stale()
    if a.proba:
        bledy += await proba(a.proba, a.seed)
    sys.exit(1 if bledy else 0)


asyncio.run(main())
