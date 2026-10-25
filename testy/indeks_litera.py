"""Numer artykułu z literą w indeksie (131¹ᵃ) — bez sieci (#11).

Dwie przyczyny, przez które art. 131¹ᵃ k.p.c. „na dzień” 01.10.2024 dawał
treść art. 131: (1) _art_regex gubił indeks z literą („131[1a]” → '131'),
więc ścieżka zapasowa trafiała w „Art. 131.”; (2) t.j. 2024 znakuje artykuł
jako data-id="arti_131_1_a", a klucz to '131_1a' — artykuł nie był widziany
w znacznikach i szedł ścieżką zapasową, która nie sprawdza dat.

    python testy/indeks_litera.py
"""
import pathlib, re, sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from legal_cite import core

bledy = 0


def sprawdz(ok: bool, opis: str) -> None:
    global bledy
    bledy += not ok
    print("ok " if ok else "ZLE", opis)


T = ("Art. 131. § 1. Sąd doręcza. Art. 131 1 . § 1. Jeden. Art. 131 1 a . § 1. Portal. "
     "Art. 36a. Lit. Art. 385 1 . Klauzule.")
for art, oczek in [("131", "Art. 131. §"), ("131¹", "Art. 131 1 . §"), ("131¹ᵃ", "Art. 131 1 a"),
                   ("131[1a]", "Art. 131 1 a"), ("131(1a)", "Art. 131 1 a"), ("36a", "Art. 36a."),
                   ("385¹", "Art. 385 1 .")]:
    m = re.search(rf"Art\.\s*{core._art_regex(art)}\s*\.", T)
    sprawdz(bool(m) and T[m.start():].startswith(oczek), f"_art_regex({art!r}) → {oczek!r}")
sprawdz(not re.search(rf"Art\.\s*{core._art_regex('x1')}\s*\.", T), "nierozpoznany numer nie trafia w nic")
sprawdz(core.extract_pl_article("Art. 130. A. Art. 131. § 1. Sąd doręcza. Art. 132. B.", "131[1a]", None) is None,
        "brak art. 131¹ᵃ w tekście → None, nie art. 131")

HTML = ('<div class="unit unit_arti pro-text false" id="arti_131" data-id="arti_131"><h3><B>Art.&nbsp;131.</B></h3>'
        '<div class="unit-inner">Sąd doręcza przez operatora pocztowego.</div></div>'
        '<div class="unit unit_arti pro-text false" id="arti_131_1_a" data-id="arti_131_1_a"><h3><B>Art.&nbsp;131<sup>1a</sup>.</B></h3>'
        '<div class="unit-inner">W razie niemożności doręczenia sąd doręcza.</div></div>')
nr = [n for n, *_ in core._jednostki_html("test-131-1-a", HTML)]
sprawdz(nr == ["131", "131_1a"], f"data-id arti_131_1_a → klucz 131_1a: {nr}")
w = core.extract_pl_article_html("test-131-1-a", HTML, "131¹ᵃ", None)
sprawdz(w is not None and "niemożności doręczenia" in w and "operatora" not in w, "extract art. 131¹ᵃ po znaczniku")

print("wszystko OK" if not bledy else f"{bledy} błędów")
sys.exit(1 if bledy else 0)
