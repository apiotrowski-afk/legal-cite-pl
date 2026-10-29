"""Losowa próba obowiązujących aktów UE (rozporządzenia, dyrektywy) — kontrola struktury, sieć.

Dla każdego aktu z próby narzędzie dostaje kolejno „art. k CELEX X” (k = 1, 2, …,
do trzech braków z rzędu). Artykuł jest ok, gdy treść zaczyna się od „Artykuł k”
i nie zawiera nagłówka innego artykułu; inaczej błąd struktury (sklejone albo
ucięte artykuły). Odmowy pobrania liczone osobno. Drugiego, niezależnego źródła
tekstu UE nie ma (EUR-Lex i CELLAR to ten sam Urząd Publikacji), więc to kontrola
granic artykułów, nie porównanie brzmień.

    python testy/pokrycie_ue.py [--n 100] [--seed 2026]
"""
import argparse, asyncio, pathlib, random, re, sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from legal_cite import core

Q = """PREFIX cdm: <http://publications.europa.eu/ontology/cdm#>
SELECT DISTINCT ?celex WHERE {
 ?w cdm:resource_legal_id_celex ?celex ; cdm:resource_legal_in-force ?f ; cdm:work_has_resource-type ?t .
 FILTER(STR(?f) IN ("1","true"))
 FILTER(?t IN (<http://publications.europa.eu/resource/authority/resource-type/REG>,
               <http://publications.europa.eu/resource/authority/resource-type/DIR>))
 FILTER(REGEX(STR(?celex), "^3(19[6-9]|20[0-2])[0-9][RL][0-9]{4}$"))
} LIMIT 40000"""
NAGL = re.compile(core._NAGLOWEK_ART_EU + r'(\d+[a-z]?)(?![\w])')


async def akt(celex: str) -> dict:
    w = {"celex": celex, "ok": 0, "struktura": [], "odmowa": None}
    braki, k = 0, 0
    while braki < 3 and k < 600:
        k += 1
        r = await core.verify_article(f"art. {k} CELEX {celex}")
        if r.startswith("❌"):
            if "nie znaleziony" in r:
                braki += 1
                continue
            w["odmowa"] = r[:220].replace("\n", " ")
            break
        braki = 0
        tresc = r.split("\n\n", 1)[1].rsplit("\n\n[dla modelu]", 1)[0]
        naglowki = NAGL.findall(tresc)
        if not tresc.startswith(f"Artykuł {k}") or any(n != str(k) for n in naglowki):
            w["struktura"].append(k)
        else:
            w["ok"] += 1
    return w


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=100)
    ap.add_argument("--seed", type=int, default=2026)
    a = ap.parse_args()
    wszystkie = sorted(x["celex"] for x in await core._sparql(Q))
    proba = random.Random(a.seed).sample(wszystkie, min(a.n, len(wszystkie)))
    print(f"obowiązujące rozporządzenia i dyrektywy 1960–2029: {len(wszystkie)}; próba {len(proba)} (seed {a.seed})")
    suma = {"akty": 0, "ok": 0, "struktura": 0, "bez_wersji_pl": 0, "odmowy": 0}
    for c in proba:
        w = await akt(c)
        suma["akty"] += 1; suma["ok"] += w["ok"]; suma["struktura"] += len(w["struktura"])
        bez_pl = bool(w["odmowa"]) and "polskiej wersji" in w["odmowa"]
        suma["bez_wersji_pl"] += bez_pl
        suma["odmowy"] += bool(w["odmowa"]) and not bez_pl
        if w["struktura"] or w["odmowa"]:
            print(f"  {c}: ok {w['ok']}, struktura {w['struktura'][:10]}, odmowa {w['odmowa']}")
    print(suma)
    sys.exit(1 if suma["struktura"] else 0)


asyncio.run(main())
