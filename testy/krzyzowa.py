"""Krzyżowa kontrola dwóch niezależnych metod wycinania artykułu.

Ścieżka produkcyjna idzie po znacznikach jednostek redakcyjnych źródła
(`data-id="arti_N"`), zapasowa szuka nagłówka „Art. N." w tekście. Metody są
od siebie niezależne, więc zgodność na kilku tysiącach artykułów jest mocnym
argumentem, a każda rozbieżność wymaga oceny ręcznej.

    python testy/krzyzowa.py

Stan na 2026-10-03: 5803 zgodne, 3 rozbieżności i wszystkie zamierzone —
art. 15 k.p.c. (źródło zlepia numer z odnośnikiem, znajduje tylko struktura)
oraz art. 3b u.ś.u.d.e. dwukrotnie (dwa brzmienia; struktura bierze
obowiązujące, ścieżka tekstowa brała dłuższe, czyli przyszłe).
"""
import asyncio, pathlib, re, sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from legal_cite import core


def norm(s):
    return re.sub(r'\s+', ' ', s or '').strip()


def cytat(num):
    if '_' in num:
        baza, idx = num.split('_', 1)
        return f'{baza}[{idx}]' if idx.isdigit() else None
    return num if re.fullmatch(r'\d+[a-z]?', num) else None


async def main():
    laczne = dict(zgoda=0, tylko_struktura=0, tylko_tekst=0, rozne=0, brak_obu=0)
    rozbieznosci = []
    for kod in ['KC', 'KP', 'KSH', 'KPC', 'KK', 'PrAut', 'u.r.p.',
                'u.ś.u.d.e.', 'u.z.n.k.', 'u.p.k.', 'UODO', 'u.k.k.']:
        info = core.PL_ACTS[kod]
        core._cache.clear(); core._html_cache.clear()
        core._jedn_cache.clear(); core._trzon_cache.clear()
        text = await core._fetch_pl(info)
        key = core._klucz_pl(info)
        raw = core._html_cache[key]
        w = dict(zgoda=0, tylko_struktura=0, tylko_tekst=0, rozne=0, brak_obu=0)
        for num, _ in core._jednostki_html(key, raw):
            art = cytat(num)
            if not art:
                continue
            a = core.extract_pl_article_html(key, raw, art, None)
            b = core.extract_pl_article(text, art, None)
            if a:
                a = a.split('\n\n⚠')[0]
            if a is None and b is None:
                w['brak_obu'] += 1
            elif a is None:
                w['tylko_tekst'] += 1
                rozbieznosci.append((kod, art, 'TYLKO TEKST', norm(b)[:90]))
            elif b is None:
                w['tylko_struktura'] += 1
                rozbieznosci.append((kod, art, 'TYLKO STRUKTURA', norm(a)[:90]))
            elif norm(b).startswith(norm(a)[:120]) or norm(a).startswith(norm(b)[:120]):
                w['zgoda'] += 1
            else:
                w['rozne'] += 1
                rozbieznosci.append((kod, art, 'ROZNE', f'str={norm(a)[:70]!r} txt={norm(b)[:70]!r}'))
        for k in w:
            laczne[k] += w[k]
        print(f"{kod:12s} zgoda={w['zgoda']:5d} tylko_str={w['tylko_struktura']:4d} "
              f"tylko_txt={w['tylko_tekst']:4d} rozne={w['rozne']:4d} brak_obu={w['brak_obu']:4d}",
              flush=True)
    print('\n=== SUMA', laczne, '\nrozbieżności:', len(rozbieznosci))
    for r in rozbieznosci[:60]:
        print('  ', r[0], 'art.', r[1], r[2], '|', r[3][:100])


asyncio.run(main())
