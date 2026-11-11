"""Akt ze statusem „akt jednorazowy” w ELI: brzmienie z ostrzeżeniem, nie odmowa — sieć.

ELI oznacza takie akty jako obowiązujące (IN_FORCE); jednorazowość znaczy, że akt
dotyczy jednego zdarzenia. Odmowa zostaje dla aktów uchylonych i wygasłych.
Stres-test 9.11.2026: 53 odmowy „akt jednorazowy”; decyzja 11.11.2026.

    python testy/akt_jednorazowy.py
"""
import asyncio, pathlib, sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from legal_cite import core

bledy = 0


def sprawdz(ok, opis):
    global bledy
    bledy += not ok
    print("ok " if ok else "ZLE", opis)


async def main():
    # ustawa o utworzeniu Akademii Piotrkowskiej — normy stosowane do dziś
    r = await core.verify_article("art. 3 Dz.U. 2023 poz. 709")
    sprawdz(r.startswith(("📜", "📄")) and "Art. 3." in r, "jednorazowa ustawa: brzmienie podane")
    sprawdz("⚠ Akt jednorazowy" in r and "akt_jednorazowy=tak" in r, "jednorazowa ustawa: ostrzeżenie i pole dla modelu")
    # rozporządzenie o obszarze Natura 2000 (paragrafy)
    r = await core.verify_article("§ 3 Dz.U. 2023 poz. 876")
    sprawdz(r.startswith(("📜", "📄")) and "⚠ Akt jednorazowy" in r, "jednorazowe rozporządzenie: brzmienie z ostrzeżeniem")
    # akt zwykły — bez ostrzeżenia
    r = await core.verify_article("art. 1 Dz.U. 2024 poz. 1061")
    sprawdz("Akt jednorazowy" not in r and "akt_jednorazowy" not in r, "zwykły akt: bez ostrzeżenia")
    # uchylony — nadal odmowa
    r = await core.verify_article("art. 2 ustawy z dnia 29 sierpnia 1997 r. o ochronie danych osobowych")
    sprawdz(r.startswith("❌"), "uchylony: nadal odmowa")


asyncio.run(main())
print("BŁĘDÓW:", bledy)
sys.exit(1 if bledy else 0)
