"""Wady HTML tekstów jednolitych w ELI, przed którymi broni się wycinanie artykułu — bez sieci.

Przypadki z masowego testu „na dzień” (2026-11-10, osiem kodeksów, ok. 25 tys. zapytań):
- rozdział zagnieżdżony w § artykułu (k.p.c., t.j. Dz.U. 2014 poz. 101, art. 15);
- wyśrodkowany nagłówek „CZĘŚĆ WOJSKOWA” w § 2 art. 316 k.k. (t.j. 2016);
- zabłąkany przypis „(Dz. U. poz. 1638).” w art. 430 k.c. (t.j. 2020);
- glosa z wykazem dyrektyw w art. 516 k.s.h. (t.j. 2013);
- „l” i „1” zamienione w numerze: `arti_5891` = art. 589l, `arti_61ls` = art. 611s (k.p.k., t.j. 2016).

    python testy/wady_html_eli.py
"""
import pathlib, sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from legal_cite import core


def art(num, wnetrze):
    return (f'<div class="unit unit_arti pro-text false" id="book_I-arti_{num}" data-id="arti_{num}">'
            f'<h3 CLASS="pro-none"><B CLASS="b">Art.&nbsp;{num}.</B></h3><div class="unit-inner">{wnetrze}</div></div>')


def tekst(t):
    return f'<div data-template="xText" CLASS="pro-text">{t}</div>'


HTML = "".join([
    art("15", tekst("Sąd właściwy pozostaje właściwy.")
        + '<div class="unit unit_chpt pro-text with-title" id="x-chpt_1" data-id="chpt_1"><h3>Rozdział 1 Właściwość rzeczowa</h3></div>'),
    art("316", tekst("Podrobione znaki należy usunąć.")
        + '<div data-template="xText" CLASS="pro-text" ALIGN="center"><B CLASS="b">CZĘŚĆ WOJSKOWA</B></div>'),
    art("430", tekst("Kto na własny rachunek powierza wykonanie czynności.") + tekst("(Dz. U. poz. 1638).")),
    art("516", tekst("Połączenie może być przeprowadzone.")
        + '<div class="unit unit_none pro-gloss-inner false" id="g" data-id="none_8"><h3>8)</h3>'
          '<div class="unit-inner">dyrektywy 2001/24/WE</div></div>'),
    art("589k", tekst("K.")), art("5891", tekst("Wykonuje niezwłocznie.")), art("589m", tekst("M.")),
    art("611r", tekst("R.")), art("61ls", tekst("Ustaleń z Trybunałem dokonuje Minister.")), art("611t", tekst("T.")),
    art("700", tekst("Siedemset.")), art("701", tekst("Siedemset jeden.")), art("702", tekst("Siedemset dwa.")),
])
jedn = {n: t for n, t, _ in core._jednostki_html("test-wady-html", HTML)}

PRZYPADKI = [
    ("15", "właściwy", "Rozdział"),
    ("316", "usunąć", "WOJSKOWA"),
    ("430", "czynności", "1638"),
    ("516", "przeprowadzone", "2001/24"),
    ("589l", "niezwłocznie", None),
    ("611s", "Trybunałem", None),
    ("701", "jeden", None),          # zwykły numer z „1” na końcu — bez zmian
]
bledy = 0
for num, musi, nie in PRZYPADKI:
    t = jedn.get(num)
    ok = t is not None and musi in t and (nie is None or nie not in t)
    bledy += not ok
    print("ok " if ok else "ZLE", f"art. {num}: {t!r}")
for zly in ("5891", "61ls", "70l"):
    ok = zly not in jedn
    bledy += not ok
    print("ok " if ok else "ZLE", f"brak klucza {zly}")
print(f"\n{len(PRZYPADKI) + 3 - bledy}/{len(PRZYPADKI) + 3}")
sys.exit(1 if bledy else 0)
