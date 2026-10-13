"""Wierność odczytu PDF: każdy artykuł tekstu jednolitego z PDF przez kontrole.

Dla aktów, których najnowszy tekst jednolity jest tylko w PDF, konwertujemy
go eli2md i dla każdego artykułu sprawdzamy: (1) zgodność z warstwą tekstową
PDF czytaną przez pdftotext, (2) stosunek do starszego t.j. w HTML
(identyczny / różny z odnośnikiem / różny bez odnośnika / nowy).

    python testy/pdf_wiernosc.py [KOD ...]      # domyślnie wszystkie PDF-only

Wymaga eli2md i pdftotext; pierwsza konwersja kodeksu trwa do ~1,5 min.

Stan na 2026-10-10 (8 aktów, 4676 artykułów): kontrola pdftotext zaliczona
4674, niezaliczona 2 (art. 6³ PrAut, art. 2 u.p.k. — oba identyczne ze
starszym HTML, więc narzędzie i tak oddaje tekst urzędowy); względem HTML:
identycznych 4340, różnych z odnośnikiem 119, różnych bez odnośnika 62
(nowelizacje między tekstami jednolitymi), nowych 155. Numery artykułów
monotoniczne we wszystkich 8 aktach.
Stan na 2026-10-11 (10 aktów, z k.r.o. i u.k.s.c.; 5390 artykułów): pdftotext
zaliczona 5388; wybór brzmienia podjednostek w 12 artykułach, 0 niejednoznacznych.
Stan na 2026-10-13 (eli2md 0.6.54, pdftotext 24.02; 10 aktów, 5124 artykuły —
o 30 więcej, bo doszły numery z dwiema literami: 59aa, 43ba, 7aa): pdftotext
zaliczona 5124/5124 (8 aktów z 10.10: 4706/4706). Pominięte słowa warstwy
tłumaczy już tylko nagłówek strony albo cały przypis w tym miejscu, a nie
samo wystąpienie słowa w którymś przypisie aktu.
"""
import asyncio, collections, pathlib, sys, time
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from legal_cite import core, pdf_tj


async def main(kody):
    for kod in kody:
        info = core.PL_ACTS[kod]
        t0 = time.time()
        tj = await core._teksty_jednolite(info)
        najnowszy = tj[0]
        if najnowszy["html"]:
            print(f"{kod}: najnowszy t.j. {najnowszy['id']} ma HTML — ścieżka PDF nieużywana")
            continue
        od = await pdf_tj.odczyt(najnowszy["id"], najnowszy.get("meta"))
        # starszy HTML do porównania
        text = await core._fetch_pl(info)
        key = core._klucz_pl(info)
        if key not in core._zrodlo:
            print(f"{kod}: API ELI nie oddaje starszego t.j. w HTML — pomiar pominięty")
            continue
        html = core._jednostki_html(key, core._html_cache[key]) if key in core._html_cache else []
        po_num = collections.defaultdict(list)
        for n, t, _ in html:
            po_num[n].append(t)
        w = collections.Counter()
        bledy = []
        for j in od.jednostki:
            wyn = pdf_tj.wiernosc_pdftotext(j, od.raw_tok, od.wyjasnienia)
            if not wyn.ok:
                w["pdftotext_ZLE"] += 1
                bledy.append((j.num, wyn.powod[:110]))
            else:
                w["pdftotext_ok"] += 1
            rel = pdf_tj.porownaj_z_html(j, po_num.get(j.klucz, []))
            if rel == "rozny":
                rel = "rozny_z_odnosnikiem" if j.odnosniki else "rozny_BEZ_odnosnika"
            w[rel] += 1
            if rel == "rozny_BEZ_odnosnika":
                bledy.append((j.num, "RÓŻNY BEZ ODNOŚNIKA vs HTML: " + j.tekst[:90]))
        print(f"\n{kod:10s} {najnowszy['id']} ({od.adres}, {od.data_tj}) vs HTML {core._zrodlo[key][0]} "
              f"| art={len(od.jednostki)} monotonicznie={od.monotoniczne} | {dict(w)} | {time.time()-t0:.0f}s")
        for b in bledy[:40]:
            print("   art.", b[0], "|", b[1])
    print()


kody = sys.argv[1:] or ["KP", "KC", "KPC", "KK", "PrAut", "u.z.n.k.", "u.p.k.", "u.k.k.", "KRO", "u.k.s.c."]
asyncio.run(main(kody))
