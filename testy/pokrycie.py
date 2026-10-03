"""Pokrycie: każdy artykuł aktu musi być osiągalny pod swoim numerem.

Wzorcem jest struktura HTML api.sejm.gov.pl (`data-id="arti_N"`), nie nasz
regex — dla każdego artykułu z trzonu aktu (id bez prefiksu `pass_`, czyli nie
przepis przejściowy ustawy nowelizującej) porównujemy wynik produkcyjnej
ścieżki wycinania z treścią tej jednostki redakcyjnej.

    python testy/pokrycie.py [plik-wyniku.json]

Artykuły, dla których tekst jednolity podaje dwa brzmienia (obowiązujące i
to wchodzące w życie z nowelizacją), wychodzą tu jako ZLE — wzorzec jest
naiwny i bierze każdą jednostkę po kolei, a narzędzie świadomie zwraca
brzmienie obowiązujące. Stan na 2026-10-03: 5801 OK, 0 odmów, 5 takich flag.
"""
import asyncio, json, pathlib, re, sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from legal_cite import core

_orig_strip = core._strip_html
RAW = {}


def _spy(raw):
    RAW['last'] = raw
    return _orig_strip(raw)


core._strip_html = _spy

UNIT = re.compile(r'<div class="unit unit_arti[^"]*" id="([^"]*)" data-id="arti_([^"]+)"')


def jednostki(raw):
    ms = list(UNIT.finditer(raw))
    for i, m in enumerate(ms):
        end = ms[i + 1].start() if i + 1 < len(ms) else len(raw)
        yield m.group(1), m.group(2), _orig_strip(raw[m.start():end])


def cytat(num):
    """arti_385_1 → 'art. 385[1]', arti_3a → 'art. 3a', arti_15 → 'art. 15'."""
    if '_' in num:
        baza, idx = num.split('_', 1)
        if idx.isdigit():
            return f'{baza}[{idx}]'
        return None
    return num if re.fullmatch(r'\d+[a-z]?', num) else None


def norm(s):
    return re.sub(r'\s+', ' ', s or '').strip()


async def main():
    akty = []
    for kod in dict.fromkeys(core.PL_ACTS):
        info = core.PL_ACTS[kod]
        if info['name'] in [a[1]['name'] for a in akty]:
            continue
        akty.append((kod, info))
    sumy = dict(ok=0, zle=0, odmowa=0, pominiete=0)
    raport = []
    for kod, info in akty:
        core._cache.clear()
        core._trzon_cache.clear(); core._html_cache.clear(); core._jedn_cache.clear(); core._zlepki.clear()
        text = await core._fetch_pl(info)
        raw = RAW['last']
        wyniki = dict(ok=0, zle=0, odmowa=0, pominiete=0)
        bledy = []
        for ident, num, tresc in jednostki(raw):
            if 'pass_' in ident:
                continue
            art = cytat(num)
            if not art:
                wyniki['pominiete'] += 1
                sumy['pominiete'] += 1
                continue
            key = core._klucz_pl(info)
            raw2 = core._html_cache.get(key)
            got = core.extract_pl_article_html(key, raw2, art, None) if raw2 else None
            if got is None:
                got = core.extract_pl_article(text, art, None)
            if got:
                got = got.split(chr(10) + chr(10) + chr(9888))[0]
            oczek = norm(tresc)
            if got is None:
                wyniki['odmowa'] += 1
                sumy['odmowa'] += 1
                bledy.append(('ODMOWA', art, oczek[:70]))
            elif oczek.startswith(norm(got)[:90]) or norm(got).startswith(oczek[:90]):
                wyniki['ok'] += 1
                sumy['ok'] += 1
            else:
                wyniki['zle'] += 1
                sumy['zle'] += 1
                bledy.append(('ZLE', art, f'oczek={oczek[:60]!r} got={norm(got)[:60]!r}'))
        raport.append((kod, info['name'], wyniki, bledy))
        print(f"{kod:12s} ok={wyniki['ok']:5d} ZLE={wyniki['zle']:4d} "
              f"ODMOWA={wyniki['odmowa']:4d} pom.={wyniki['pominiete']:4d}", flush=True)
    print('\n=== SUMA', sumy)
    for kod, nazwa, w, bledy in raport:
        if bledy:
            print(f'\n--- {kod} ({len(bledy)}):')
            for b in bledy[:25]:
                print('   ', b[0], 'art.', b[1], '|', b[2])
    json.dump([[k, n, w, b] for k, n, w, b in raport],
              open(sys.argv[1] if len(sys.argv) > 1 else '/tmp/harness.json', 'w'),
              ensure_ascii=False)


asyncio.run(main())
