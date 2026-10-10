"""Awaria API ELI — bez sieci, na atrapie HTTP.

Gdy metadane mówią, że t.j. ma HTML, a API odpowiada 5xx, narzędzie odmawia
(„awaria po stronie api.sejm.gov.pl”) i NIE zapamiętuje listy tekstów
jednolitych — po powrocie API kolejne wywołanie działa bez restartu.

    python testy/awaria_api.py
"""
import asyncio, pathlib, sys, httpx
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from legal_cite import core

stan = {"html": False}


def handler(req):
    u = str(req.url)
    if u.endswith("/DU/2000/1037"):
        return httpx.Response(200, json={"references": {"Inf. o tekście jednolitym": [{"id": "DU/2024/18"}]}})
    if u.endswith("/DU/2024/18"):
        return httpx.Response(200, json={"textHTML": True, "announcementDate": "2023-12-07"})
    if u.endswith("/text.html"):
        if stan["html"] and "2024/18" in u:
            return httpx.Response(200, text='<div class="unit unit_arti" id="a1" data-id="arti_1">'
                                  '<b>Art.&nbsp;1.</b> ' + "Ustawa reguluje tworzenie spółek. " * 100 + "</div>")
        return httpx.Response(500, text="err")
    return httpx.Response(200, json={})


class Mock(httpx.AsyncClient):
    def __init__(self, *a, **k):
        k["transport"] = httpx.MockTransport(handler)
        super().__init__(*a, **k)


core.httpx.AsyncClient = Mock
klucz = core._klucz_pl(core.PL_ACTS["KSH"])


async def main():
    bledy = 0
    r = await core.verify_article("art. 1 KSH")
    for ok, opis in ((r.startswith("❌") and "awaria" in r, "awaria API → jawna odmowa"),
                     (klucz not in core._tj_cache, "lista t.j. po awarii nie trafia do cache")):
        print("ok " if ok else "ZLE", opis); bledy += not ok
    stan["html"] = True
    r = await core.verify_article("art. 1 KSH")
    for ok, opis in ((r.startswith("📜"), "po powrocie API → brzmienie bez restartu"),
                     (klucz in core._tj_cache, "poprawna lista t.j. trafia do cache")):
        print("ok " if ok else "ZLE", opis); bledy += not ok
    print("\nwszystko OK" if not bledy else f"\n{bledy} błędów")
    sys.exit(1 if bledy else 0)


asyncio.run(main())
