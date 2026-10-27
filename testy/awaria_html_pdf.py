"""Tryb awaryjny: HTML ELI nie odpowiada, PDF działa — sieć.

26.10.2026 wszystkie adresy …/text.html API ELI zwracały 500, a metadane i PDF
działały. Narzędzie odmawiało wtedy dla KC, KP i innych aktów, których odczyt
PDF porównuje się ze starszym t.j. w HTML. Od 27.10.2026: odczyt PDF z kontrolą
warstwy tekstowej, jawnie oznaczony („NIEWYKONANE — … awaria”), zamiast odmowy.
Atrapa przepuszcza ruch do API, zwracając 500 tylko dla text.html.

    python testy/awaria_html_pdf.py
"""
import asyncio, pathlib, sys, httpx
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from legal_cite import core

_prawdziwy = httpx.AsyncHTTPTransport()


class Awaria(httpx.AsyncBaseTransport):
    async def handle_async_request(self, req):
        if str(req.url).endswith("/text.html"):
            return httpx.Response(500, text="err", request=req)
        return await _prawdziwy.handle_async_request(req)


class Mock(httpx.AsyncClient):
    def __init__(self, *a, **k):
        k["transport"] = Awaria()
        super().__init__(*a, **k)


core.httpx.AsyncClient = Mock
bledy = 0


def sprawdz(ok: bool, opis: str) -> None:
    global bledy
    bledy += not ok
    print("ok " if ok else "ZLE", opis)


async def main():
    r = await core.verify_article("art. 734 KC")
    sprawdz(r.startswith("📄") and "NIEWYKONANE" in r and "awaria" in r and "Art. 734" in r,
            "KC (najnowszy t.j. tylko w PDF): odczyt PDF z adnotacją o awarii")
    sprawdz("wiernosc=zaliczona_pdftotext_bez_porownania_html_awaria_eli" in r, "pole wiernosc dla modelu")
    r = await core.verify_article("art. 2 u.f.r.")
    sprawdz(r.startswith("📄") and "NIEWYKONANE" in r, "u.f.r. (najnowszy t.j. w HTML): odczyt PDF tego t.j.")
    print("wszystko OK" if not bledy else f"{bledy} błędów")
    return bledy


sys.exit(1 if asyncio.run(main()) else 0)
