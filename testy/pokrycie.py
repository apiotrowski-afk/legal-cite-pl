"""Pokrycie: każdy artykuł aktu musi być osiągalny pod swoim numerem.

Wzorcem jest struktura HTML api.sejm.gov.pl (`data-id="arti_N"`), nie nasz
regex — dla każdego numeru artykułu z trzonu aktu (id bez prefiksu `pass_`,
czyli nie przepis przejściowy ustawy nowelizującej) sprawdzamy, czy produkcyjna
ścieżka wycinania zwraca treść TEJ jednostki redakcyjnej.

    python testy/pokrycie.py [plik-wyniku.json]

Artykuł drukowany w kilku brzmieniach (obowiązującym i tym, które wejdzie w
życie z nowelizacją) zaliczamy, gdy wynik odpowiada któremukolwiek z nich, a
osobno wypisujemy, które brzmienie wybrano i od kiedy obowiązuje — to jest
właściwy przedmiot oceny, bo tekst jednolity zamraża stan prawny na dzień
obwieszczenia, a nowelizacja mogła wejść w życie później.

Stan na 2026-10-04: 5801 OK, 0 odmów, 0 błędnych brzmień.
"""
import asyncio, collections, json, pathlib, re, sys

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
    """Numer artykułu → lista brzmień, w kolejności druku."""
    po = collections.OrderedDict()
    for m in UNIT.finditer(raw):
        if 'pass_' in m.group(1):
            continue
        tresc = _orig_strip(raw[m.start():core._koniec_div(raw, m.start())])
        po.setdefault(m.group(2).lower(), []).append(tresc)
    return po


def cytat(num):
    """arti_385_1 → 'art. 385[1]', arti_3a → 'art. 3a', arti_15 → 'art. 15'."""
    if '_' in num:
        baza, idx = num.split('_', 1)
        return f'{baza}[{idx}]' if idx.isdigit() else None
    return num if re.fullmatch(r'\d+[a-ząćęłńóśźż]?', num) else None


def norm(s):
    return re.sub(r'\s+', ' ', s or '').strip()


async def main():
    akty, widziane = [], set()
    for kod in dict.fromkeys(core.PL_ACTS):
        nazwa = core.PL_ACTS[kod]['name']
        if nazwa not in widziane:
            widziane.add(nazwa)
            akty.append((kod, core.PL_ACTS[kod]))

    sumy = collections.Counter()
    raport, wielobrzmieniowe = [], []
    for kod, info in akty:
        for pamiec in (core._cache, core._html_cache, core._jedn_cache,
                       core._trzon_cache, core._odn_cache, core._zlepki):
            pamiec.clear()
        text = await core._fetch_pl(info)
        raw = RAW['last']
        key = core._klucz_pl(info)
        w, bledy = collections.Counter(), []
        for num, brzmienia in jednostki(raw).items():
            art = cytat(num)
            if not art:
                w['pominiete'] += 1
                continue
            got = core.extract_pl_article_html(key, raw, art, None)
            if got is None:
                got = core.extract_pl_article(text, art, None)
            if got:
                got = got.split('\n\n⚠')[0]
            if len(brzmienia) > 1:
                wybrane = next((i for i, b in enumerate(brzmienia)
                                if norm(b).startswith(norm(got)[:90])), None)
                daty = [d for n, _, d in core._jednostki_html(key, raw) if n == num]
                wielobrzmieniowe.append((kod, art, len(brzmienia), wybrane, daty))
            if got is None:
                w['odmowa'] += 1
                bledy.append(('ODMOWA', art, norm(brzmienia[0])[:70]))
            elif any(norm(b).startswith(norm(got)[:90])
                     or norm(got).startswith(norm(b)[:90]) for b in brzmienia):
                w['ok'] += 1
            else:
                w['zle'] += 1
                bledy.append(('ZLE', art,
                              f'wzorce={[norm(b)[:40] for b in brzmienia]} got={norm(got)[:50]!r}'))
        sumy.update(w)
        raport.append((kod, info['name'], dict(w), bledy))
        print(f"{kod:12s} ok={w['ok']:5d} ZLE={w['zle']:4d} ODMOWA={w['odmowa']:4d} "
              f"pom.={w['pominiete']:4d}", flush=True)

    print('\n=== SUMA', dict(sumy))
    print('\n--- artykuły o kilku brzmieniach (wybór = indeks brzmienia, daty wejścia w życie):')
    for kod, art, ile, wybrane, daty in wielobrzmieniowe:
        opis = ', '.join(str(d) if d else 'w dniu t.j.' for d in daty)
        print(f'   {kod:12s} art. {art:10s} brzmień={ile} wybrano={wybrane}  [{opis}]')
    for kod, nazwa, w, bledy in raport:
        if bledy:
            print(f'\n--- {kod} ({len(bledy)}):')
            for b in bledy[:25]:
                print('   ', b[0], 'art.', b[1], '|', b[2])
    json.dump([[k, n, w, b] for k, n, w, b in raport],
              open(sys.argv[1] if len(sys.argv) > 1 else '/tmp/pokrycie.json', 'w'),
              ensure_ascii=False)


asyncio.run(main())
