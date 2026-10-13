"""Nagłówek oddziału nie jest tekstem artykułu, który go poprzedza — bez sieci.

eli2md 0.6.49 nie rozpoznawał nagłówka oddziału z indeksem górnym, odnośnikiem
i tytułem w jednym wierszu („Oddział 2¹[^14] Dostawcy usług…”), więc doklejał
go do poprzedniego artykułu: pr. aut. art. 22, 35, 35¹⁸, 35²¹ i 99⁶ w t.j.
Dz.U. 2025 poz. 24 („Art. 22. (uchylony) Oddział 2¹ Dostawcy usług…”), a
odnośnik nagłówka stawał się odnośnikiem artykułu. Poprawione w konwerterze
od 0.6.50; ten test pilnuje przypiętej wersji. Treść poniżej jest fikcyjna.

    python testy/naglowek_oddzialu.py
"""
import pathlib
import re
import sys
from importlib.metadata import version

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from legal_cite import pdf_tj

MD = """## Załącznik

##### Art. 22.

(uchylony)

Oddział 2¹[^14] Dostawcy usług oświetlania wybrzeża

##### Art. 22¹.

1. Dostawca usług oświetlania wybrzeża prowadzi rejestr latarni.

2. Rejestr latarni jest jawny i nie może naruszać interesów latarnika.

Oddział 3¹[^19] Dozwolone korzystanie z latarni

##### Art. 23.

Z latarni wolno korzystać nieodpłatnie.

Rozdział 4

Przepisy końcowe

##### Art. 24.

Ustawa wchodzi w życie po upływie 14 dni od dnia ogłoszenia.

[^14]: Oddział dodany przez art. 1 pkt 7 ustawy z dnia 3 marca 2020 r. (Dz. U. poz. 5).

[^19]: Oddział dodany przez art. 1 pkt 9 ustawy, o której mowa w odnośniku 14.
"""

bledy = 0


def sprawdz(ok: bool, opis: str) -> None:
    global bledy
    bledy += not ok
    print("ok " if ok else "ZLE", opis)


jedn, monotonicznie = pdf_tj.jednostki_md(MD, pdf_tj.przypisy_md(MD))
po = {j.klucz: j for j in jedn}
sprawdz(list(po) == ["22", "22_1", "23", "24"] and monotonicznie, f"artykuły: {list(po)}")
sprawdz(po["22"].czysty() == "Art. 22. (uchylony)", f"art. 22: {po['22'].czysty()!r}")
sprawdz(po["22"].odnosniki == [], "odnośnik nagłówka oddziału nie jest odnośnikiem art. 22")
sprawdz(po["22_1"].czysty().endswith("interesów latarnika.") and po["22_1"].odnosniki == [],
        f"art. 22¹ kończy się swoją treścią: …{po['22_1'].czysty()[-45:]!r}")
sprawdz(po["23"].czysty() == "Art. 23. Z latarni wolno korzystać nieodpłatnie.",
        f"art. 23 bez nagłówka rozdziału: {po['23'].czysty()!r}")

# przypięta wersja konwertera = zainstalowana (od niej zależy klucz cache i powtarzalność)
pyproject = (pathlib.Path(__file__).resolve().parents[1] / "pyproject.toml").read_text(encoding="utf-8")
pin = re.search(r"eli2md@v([\d.]+)", pyproject).group(1)
sprawdz(version("eli2md") == pin, f"eli2md zainstalowany {version('eli2md')}, przypięty {pin}")

print("\nwszystko OK" if not bledy else f"\nbłędów: {bledy}")
sys.exit(1 if bledy else 0)
