"""Nagłówek artykułu wklejony w treść poprzedniego — bez sieci (#7).

T.j. u.ś.u.d.e. (Dz.U. 2024 poz. 1513) drukuje „<B>Art. 15. </B>” w akapicie
art. 14 ust. 4 i nie daje art. 15 własnej jednostki, więc art. 14 oddawał też
treść art. 15. Fragmenty HTML poniżej mają budowę źródła (skrócone).

    python testy/granica_artykulu.py
"""
import pathlib, sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from legal_cite import core

bledy = 0


def sprawdz(ok: bool, opis: str) -> None:
    global bledy
    bledy += not ok
    print("ok " if ok else "ZLE", opis)


def artykul(nr: str, ustepy: list[str]) -> str:
    srodek = "".join(
        f'<div class="unit unit_pass pro-text false" id="arti_{nr}-pass_{i}" data-id="pass_{i}">'
        f'<h3 CLASS="pro-align-padding-right">{i}.</h3><div class="unit-inner">'
        f'<div data-template="xText" CLASS="pro-text">{t}</div></div></div>'
        for i, t in enumerate(ustepy, start=1))
    return (f'<div class="unit unit_arti pro-text false" id="chpt_3-arti_{nr}" data-id="arti_{nr}">'
            f'<h3 CLASS="pro-none"><B CLASS="b">Art.&nbsp;{nr}.</B></h3><div class="unit-inner">{srodek}</div></div>')


WKLEJONY = (artykul("13", ["Nie ponosi odpowiedzialności ten, kto transmituje dane."])
            + artykul("14", ["Nie ponosi odpowiedzialności za przechowywane dane ten, kto udostępnia zasoby.",
                             'Przepisów ust. 1 nie stosuje się, jeżeli usługodawca przejął kontrolę nad '
                             'usługobiorcą. <B CLASS="b">Art. 15. </B> Podmiot, który świadczy usługi '
                             'określone w art. 12-14, nie jest obowiązany do sprawdzania danych.'])
            + artykul("16", ["Usługodawca może przetwarzać dane."]))
jedn = core._jednostki_html("test-wklejony", WKLEJONY)
nr = [n for n, *_ in jedn]
tekst = {n: t for n, t, _ in jedn}
sprawdz(nr == ["13", "14", "15", "16"], f"kolejność artykułów: {nr}")
sprawdz(tekst["14"].endswith("przejął kontrolę nad usługobiorcą.") and "Art. 15" not in tekst["14"],
        f"art. 14 kończy się na swoim ust. 2: …{tekst['14'][-50:]!r}")
sprawdz(tekst.get("15", "").startswith("Art. 15. Podmiot") and tekst["15"].endswith("sprawdzania danych."),
        f"art. 15 osobno: {tekst.get('15', '')[:60]!r}")
sprawdz(tekst["13"].startswith("Art. 13.") and "Art. 14" not in tekst["13"], "art. 13 bez zmian")

# Artykuł, który ma własną jednostkę, nie jest wydzielany drugi raz z cudzej treści.
ZE_SWOJA = (artykul("14", ['Przepisów ust. 1 nie stosuje się. <B CLASS="b">Art. 15. </B> Wyróżnienie w treści.'])
            + artykul("15", ["Podmiot nie jest obowiązany do sprawdzania danych."]))
jedn = core._jednostki_html("test-ze-swoja", ZE_SWOJA)
sprawdz([n for n, *_ in jedn] == ["14", "15"], f"bez duplikatu: {[n for n, *_ in jedn]}")

# Pełna ścieżka wycinania: art. 14 i art. 15 osobno, bez sąsiada.
w14 = core.extract_pl_article_html("test-wklejony", WKLEJONY, "14", None)
w15 = core.extract_pl_article_html("test-wklejony", WKLEJONY, "15", None)
sprawdz(w14 is not None and "Art. 15" not in w14, "extract art. 14 bez art. 15")
sprawdz(w15 is not None and w15.startswith("Art. 15.") and "Art. 16" not in w15, "extract art. 15 bez art. 16")

print("wszystko OK" if not bledy else f"{bledy} błędów")
sys.exit(1 if bledy else 0)
