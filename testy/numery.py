"""Numery artykułów z kilkuliterowym sufiksem (59aa, 43ba, 7aa) — bez sieci.

Wzorzec numeru dopuszczał jedną literę, więc „art. 59aa u.k.k.” rozpadał się
na art. 59a i kod aktu „a u.k.k” → „Nieznany kod aktu”. W obsługiwanych aktach
takich artykułów jest 30: u.k.k. 26 (59aa–59ag, 59ca–59cc, 59da–59dp),
k.k. 2 (43ba, 43bb), u.p.k. 2 (7aa, 7ab).

    python testy/numery.py
"""
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from legal_cite import core, pdf_tj

CYTATY = [
    # (cytat, art, ustęp, klucz aktu)
    ("art. 59aa u.k.k.", "59aa", None, "u.k.k."),
    ("art. 59dp ust. 2 u.k.k.", "59dp", "2", "u.k.k."),
    ("art. 43ba § 1 KK", "43ba", "1", "KK"),
    ("art. 7aa ust. 1 pkt 2 u.p.k.", "7aa", "1", "u.p.k."),
    ("art. 7ab u.p.k", "7ab", None, "u.p.k."),
    # dotychczasowe zapisy bez zmian
    ("art. 59a u.k.k.", "59a", None, "u.k.k."),
    ("art. 36a KC", "36a", None, "KC"),
    ("art. 5 KC", "5", None, "KC"),
    ("art. 385¹ § 1 KC", "385[1]", "1", "KC"),
    ("art. 18[3d] KP", "18[3d]", None, "KP"),
    ("art. 131¹ᵃ § 1 k.p.c.", "131[1a]", "1", "KPC"),
]
KANON = [("59aa", "59aa"), ("43ba", "43ba"), ("7AA", "7aa"), ("36a", "36a"), ("45", "45"),
         ("385[1]", "385_1"), ("385¹", "385_1"), ("18[3d]", "18_3d"), ("a59", None)]
KANON_MD = [("59aa", "59aa"), ("43bb", "43bb"), ("36a", "36a"), ("18³ᵈ", "18_3d"),
            ("5[1q]", "5_1q"), ("22", "22"), ("266–280", None)]

bledy = 0


def sprawdz(ok: bool, opis: str) -> None:
    global bledy
    bledy += not ok
    print("ok " if ok else "ZLE", opis)


for cytat, art, ustep, akt in CYTATY:
    p = core.parse_citation(cytat)
    wynik = p and (p["art"], p["ustep"], core._resolve(p["act"], core.PL_ACTS))
    sprawdz(wynik == (art, ustep, akt), f"{cytat!r} → {wynik}")
for raw, oczekiwany in KANON:
    sprawdz(core._kanon_art(raw) == oczekiwany, f"_kanon_art({raw!r}) → {core._kanon_art(raw)}")
for raw, oczekiwany in KANON_MD:
    sprawdz(pdf_tj.kanon_md(raw) == oczekiwany, f"kanon_md({raw!r}) → {pdf_tj.kanon_md(raw)}")
# ścieżka zapasowa (regex po tekście): nagłówek „Art. 59aa.” nie myli się z „Art. 59a.”
tekst = "Art. 59a. Przepis pierwszy. Art. 59aa. Przepis drugi. Art. 59ab. Przepis trzeci."
m = re.search(rf"Art\.\s*{core._art_regex('59aa')}\s*\.", tekst)
sprawdz(bool(m) and tekst[m.start():].startswith("Art. 59aa."), "_art_regex('59aa') trafia w „Art. 59aa.”")
sprawdz(not re.search(rf"Art\.\s*{core._art_regex('59a')}\s*\.", "Art. 59aa. Przepis."),
        "_art_regex('59a') nie trafia w „Art. 59aa.”")

print("\nwszystko OK" if not bledy else f"\nbłędów: {bledy}")
sys.exit(1 if bledy else 0)
