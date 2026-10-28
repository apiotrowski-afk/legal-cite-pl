"""Dowolna ustawa po adresie Dz.U. albo tytule — rozpoznawanie adresu bez sieci, reszta z siecią.

    python testy/adres_dzu.py
"""
import asyncio, pathlib, sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from legal_cite import core

bledy = 0


def sprawdz(ok: bool, opis: str) -> None:
    global bledy
    bledy += not ok
    print("ok " if ok else "ZLE", opis)


def adres(t):
    m = core._ADRES_DZU_RE.search(t)
    return m and ((m.group(1), m.group(2)) if m.group(1) else (m.group(3), m.group(4)))


for t, oczek in [("Dz.U. 2024 poz. 1061", ("2024", "1061")), ("Dz. U. z 2024 r. poz. 1061", ("2024", "1061")),
                 ("Dz.U. 1964 nr 16 poz. 93", ("1964", "93")), ("Dz.U. z 1964 r., Nr 16, poz. 93", ("1964", "93")),
                 ("DU/2018/723", ("2018", "723")), ("ustawy z dnia 1 marca 2018 r. (Dz. U. z 2025 r. poz. 644)", ("2025", "644"))]:
    sprawdz(adres(t) == oczek, f"adres {t!r} → {oczek}")
sprawdz(adres("ustawy o KRS") is None, "bez adresu → None")


async def main():
    for cyt, jest in [("art. 734 Dz.U. 2024 poz. 1061", "Kodeks cywilny"),          # adres t.j. → akt pierwotny
                      ("art. 2 ust. 1 AML", "praniu pieniędzy"),
                      ("art. 3 DU/1997/88", "nie ustawa"),
                      ("art. 1 Dz.U. 2099 poz. 99999", "404"),
                      # katalog po tytułach
                      ("art. 9 ustawy o ochronie konkurencji i konsumentów", "z dnia 16 lutego 2007 r."),
                      ("art. 5 Prawa bankowego", "Prawo bankowe"),
                      ("art. 1 ustawy o podatku", "Nie da się jednoznacznie"),
                      # data rozstrzyga: ustawa z 1997 r. o ochronie danych osobowych uchylona
                      ("art. 2 ustawy z dnia 29 sierpnia 1997 r. o ochronie danych osobowych", "mogła zostać uchylona"),
                      ("art. 2 ustawy z dnia 10 maja 2018 r. o ochronie danych osobowych", "10 maja 2018"),
                      # akt numerowany rzymsko: „art. 1” nie może trafić w „§ 1.” cudzego artykułu
                      ("art. 1 DU/1974/142", "❌")]:
        r = await core.verify_article(cyt)
        sprawdz(jest in r, f"{cyt} → zawiera {jest!r}")


asyncio.run(main())
print("wszystko OK" if not bledy else f"{bledy} błędów")
sys.exit(1 if bledy else 0)
