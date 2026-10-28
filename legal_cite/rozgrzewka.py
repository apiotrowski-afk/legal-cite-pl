"""Nocna rozgrzewka konwersji PDF — `legal-cite-rozgrzewka` (Cloud Run Job).

Od 2025 r. najnowsze teksty jednolite są w API ELI tylko w PDF, a pierwsza
konwersja eli2md trwa 30–90 s. Serwer robi jedną konwersję naraz, więc pierwsze
zapytanie o rzadką ustawę czekało minutę lub dwie (albo dłużej w kolejce).
Zadanie przechodzi po słowniku PL_ACTS i po katalogu obowiązujących ustaw
merytorycznych z ELI i dla każdej ustawy, której najnowszy t.j. jest tylko
w PDF, wywołuje pdf_tj.odczyt — ten pobiera gotową konwersję z Cloud Storage
(LEGAL_CITE_GCS_BUCKET) albo konwertuje i ją tam zapisuje. Następna instancja
serwera pobiera wynik zamiast konwertować.

Podział na zadania równoległe: CLOUD_RUN_TASK_INDEX / CLOUD_RUN_TASK_COUNT
(ustawiane przez Cloud Run Jobs); lokalnie jedno zadanie. W logach tylko
liczniki i identyfikatory aktów.

    legal-cite-rozgrzewka [--limit N]
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import time

from legal_cite import core, pdf_tj

logger = logging.getLogger("legal_cite.rozgrzewka")


async def _akty() -> list[dict]:
    """Słownik PL_ACTS i katalog ELI, bez powtórzeń, w stałej kolejności."""
    out, widziane = [], set()
    for info in core.PL_ACTS.values():
        k = (info["year"], info["pos"])
        if k not in widziane:
            widziane.add(k)
            out.append(info)
    for x in await core._katalog_ustaw():
        k = (x["year"], x["pos"])
        if k not in widziane:
            widziane.add(k)
            out.append(dict(pub="DU", year=x["year"], pos=x["pos"], name=(x.get("title") or "")[:90]))
    return sorted(out, key=lambda i: (i["year"], i["pos"]))


async def rozgrzej(limit: int | None = None) -> dict:
    nr = int(os.environ.get("CLOUD_RUN_TASK_INDEX", "0"))
    ile = int(os.environ.get("CLOUD_RUN_TASK_COUNT", "1"))
    akty = await _akty()
    moje = [a for i, a in enumerate(akty) if i % ile == nr][:limit]
    liczniki = {"akty": len(moje), "html": 0, "pdf_gotowe": 0, "pdf_skonwertowane": 0,
                "bez_tj": 0, "bledy": 0}
    logger.info("rozgrzewka zadanie=%d/%d aktow=%d (z %d) gcs=%s",
                nr + 1, ile, len(moje), len(akty), pdf_tj.GCS_BUCKET)
    for info in moje:
        ident = f"DU/{info['year']}/{info['pos']}"
        try:
            tj = await core._teksty_jednolite(info)
            if not tj:
                liczniki["bez_tj"] += 1
                continue
            najnowszy = tj[0]
            if najnowszy["html"] or not najnowszy["meta"].get("textPDF"):
                liczniki["html"] += 1
                continue
            t0 = time.monotonic()
            await pdf_tj.odczyt(najnowszy["id"], najnowszy["meta"])
            dt = time.monotonic() - t0
            liczniki["pdf_skonwertowane" if dt > 5 else "pdf_gotowe"] += 1
            logger.info("akt=%s tj=%s czas=%.0fs", ident, najnowszy["id"], dt)
        except Exception as e:  # jeden akt nie zatrzymuje nocy
            liczniki["bledy"] += 1
            logger.warning("akt=%s blad=%s", ident, type(e).__name__)
        finally:
            # zadanie przechodzi setki aktów — odczyty nie mogą zostać w pamięci
            pdf_tj._odczyty.clear()
            core._cache.clear(); core._html_cache.clear(); core._jedn_cache.clear()
    logger.info("rozgrzewka koniec %s", liczniki)
    return liczniki


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--limit", type=int, default=None, help="najwyżej N aktów (test)")
    a = p.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    for n in ("httpx", "httpcore"):
        logging.getLogger(n).setLevel(logging.WARNING)
    if not pdf_tj.konwerter_dostepny():
        raise SystemExit("brak konwertera eli2md — rozgrzewka nie ma sensu")
    wynik = asyncio.run(rozgrzej(a.limit))
    if wynik["bledy"] > max(5, wynik["akty"] // 10):
        raise SystemExit(f"za dużo błędów: {wynik}")


if __name__ == "__main__":
    main()
