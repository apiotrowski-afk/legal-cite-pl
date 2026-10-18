"""Paragrafy i ustępy z indeksem górnym albo literą — bez sieci.

Art. 98 § 1¹ k.p.c. kończył się „Nieznany kod aktu: '[1] k.p.c'”: parser
brał indeks paragrafu za początek skrótu aktu. Przy okazji „§ 1” zabierał
§ 1¹ i § 1², a „ust. 1” — ust. 1a, bo granicą była dopiero jednostka bez
litery i indeksu. Źródła piszą indeks trzema sposobami: HTML ELI „§ 1 1 .”,
odczyt PDF „§ 1 1.”, druk 2026 „§ 1[1].”.

    python testy/indeks_paragrafu.py
"""
import pathlib, sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from legal_cite import core

bledy = 0


def sprawdz(ok: bool, opis: str) -> None:
    global bledy
    bledy += not ok
    print("ok " if ok else "ZLE", opis)


PARSER = [
    ("art. 98 § 1¹ k.p.c.", ("98", "1[1]", "k.p.c")),
    ("art. 98 § 1[1] KPC", ("98", "1[1]", "KPC")),
    ("art. 98 § 1(1) KPC", ("98", "1[1]", "KPC")),
    ("art. 98 § 1 KPC", ("98", "1", "KPC")),
    ("art. 10 ust. 1a PIT", ("10", "1a", "PIT")),
    ("art. 385¹ § 2 KC", ("385[1]", "2", "KC")),
    ("art. 131¹ᵃ § 1 k.p.c.", ("131[1a]", "1", "k.p.c")),
]
for cyt, oczek in PARSER:
    p = core.parse_citation(cyt)
    sprawdz(p and (p["art"], p["ustep"], p["act"]) == oczek, f"parser: {cyt} → {oczek}")

HTML = ("Art. 98. § 1. Strona A. § 1 1 . Od kwoty B, przewidziane w § 1 1 od kwoty. "
        "§ 1 2 . W szczególnie C. § 2. Do D.")
PDF = "Art. 5. § 1 1. Pdf A. § 1[2]. Druk B. § 1³. Sup C. § 2. D."
UST = "Art. 10. 1. Źródłami A. 1a. Za B. 1b. C. 2. D."
WYCINANIE = [
    (HTML, "1", "§ 1. Strona A."),
    (HTML, "1[1]", "§ 1 1 . Od kwoty B, przewidziane w § 1 1 od kwoty."),
    (HTML, "1[2]", "§ 1 2 . W szczególnie C."),
    (HTML, "2", "§ 2. Do D."),
    (PDF, "1[1]", "§ 1 1. Pdf A."),
    (PDF, "1[2]", "§ 1[2]. Druk B."),
    (PDF, "1[3]", "§ 1³. Sup C."),
    (UST, "1", "1. Źródłami A."),
    (UST, "1a", "1a. Za B."),
    (UST, "2", "2. D."),
]
for tekst, ust, oczek in WYCINANIE:
    w = core._cut_ustep(tekst, ust)
    sprawdz(w == oczek, f"wycinanie {ust!r}: {w!r}")

print("wszystko OK" if not bledy else f"{bledy} błędów")
sys.exit(1 if bledy else 0)
