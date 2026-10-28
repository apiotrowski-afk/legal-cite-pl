"""Pokrycie na losowej próbie ustaw z katalogu ELI — sieć (kilkadziesiąt minut).

Ocena przed otwarciem narzędzia na dowolną ustawę (adres Dz.U.): ile ustaw
spoza słownika PL_ACTS przechodzi test pokrycia bez poprawek. Próba: ustawy
obowiązujące z Dz.U. bez nowelizujących, ratyfikacyjnych, budżetowych
i jednorazowych; losowanie z ziarnem, więc przebieg jest powtarzalny.

    python testy/pokrycie_proba.py [N=100] [ziarno=2026] [plik-wyniku.json]
"""
import json, pathlib, random, runpy, sys, urllib.parse, urllib.request
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from legal_cite import core

N = int(sys.argv[1]) if len(sys.argv) > 1 else 100
ZIARNO = int(sys.argv[2]) if len(sys.argv) > 2 else 2026
WYNIK = sys.argv[3] if len(sys.argv) > 3 else "/tmp/pokrycie_proba.json"

ustawy, off = [], 0
while True:
    q = urllib.parse.urlencode({"publisher": "DU", "type": "Ustawa", "inForce": "1", "limit": 500, "offset": off})
    it = json.load(urllib.request.urlopen("https://api.sejm.gov.pl/eli/acts/search?" + q, timeout=60)).get("items", [])
    ustawy += it
    if len(it) < 500:
        break
    off += 500


def merytoryczna(x):
    t = (x.get("title") or "").lower()
    return not any(s in t for s in ("o zmianie", "o zmianach", "zmieniająca", "ratyfikacji", "ustawa budżetowa")) \
        and x.get("status") in ("akt posiada tekst jednolity", "obowiązujący")


znane = {(v["year"], v["pos"]) for v in core.PL_ACTS.values()}
pula = sorted((x for x in ustawy if merytoryczna(x) and (x["year"], x["pos"]) not in znane),
              key=lambda x: (x["year"], x["pos"]))
proba = random.Random(ZIARNO).sample(pula, min(N, len(pula)))
print(f"ustaw obowiązujących {len(ustawy)}, merytorycznych spoza słownika {len(pula)}, próba {len(proba)}",
      flush=True)
core.PL_ACTS.clear()
for x in proba:
    core.PL_ACTS[f"DU/{x['year']}/{x['pos']}"] = dict(pub="DU", year=x["year"], pos=x["pos"],
                                                      name=(x.get("title") or "")[:90])
sys.argv = [sys.argv[0], WYNIK]
runpy.run_path(str(pathlib.Path(__file__).with_name("pokrycie.py")), run_name="__main__")
