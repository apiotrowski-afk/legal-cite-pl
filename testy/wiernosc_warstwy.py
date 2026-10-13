"""Kontrola wierności na warstwie tekstowej PDF: co tłumaczy pominięte słowa — bez sieci.

Słowo warstwy, którego nie ma w odczycie artykułu, jest wytłumaczone tylko
wtedy, gdy w tym miejscu należy do nagłówka strony albo do całego przypisu
u dołu strony. Wcześniej wystarczało, że słowo występuje w dowolnym przypisie
aktu, więc kontrola przepuszczała odczyt bez słowa „kary”, jeśli „kary” było
w którymś przypisie (zgłoszenie w #3: usunięcia wykrywane w 284/317).

Warstwa i przypisy poniżej są fikcyjne (pozycja 999). Nie wymaga eli2md.

    python testy/wiernosc_warstwy.py
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from legal_cite import pdf_tj

POS = "999"
P2 = "Dodany przez art. 5 ustawy o zmianie kary grzywny."
P3 = ("W brzmieniu ustalonym przez art. 7 ustawy o latarniach morskich, która weszła w życie "
      "z dniem 1 marca 2020 r.")
P4 = "Niniejsza ustawa wdraża:\n\n    1) dyrektywę o latarniach;\n\n    2) dyrektywę o bojach."
MD_PRZYPISY = f"[^2]: {P2}\n\n[^3]: {P3}\n\n[^4]: {P4}\n\n[^5]: Utracił moc.\n"

A1 = "Art. 1. Kto niszczy cudzą latarnię, podlega karze grzywny albo karze ograniczenia wolności."
A2 = ("Art. 2. Sąd może orzec nawiązkę na rzecz pokrzywdzonego w wysokości do dziesięciu "
      "tysięcy złotych.")
A3 = ("Art. 3. Latarnik odpowiada za szkodę wyrządzoną z winy umyślnej, chyba że działał na "
      "polecenie organu wskazanego w § 7 rozporządzenia.")
A4 = "Art. 4. Podmioty, o których mowa w art. 6¹ ust. 1, składają wniosek do ministra."
A5 = ("Art. 5. Ustawa wdraża przepisy Unii Europejskiej o latarniach morskich i bojach "
      "wymienione w odnośniku.")
A6 = "Art. 6. Latarnię maluje się co pięć lat farbą bez ołowiu."

WARSTWA = "\n".join([
    "Dziennik Ustaw", "– 1 –", "Poz. 999",
    A1,
    "Art. 2.2) Sąd może orzec nawiązkę na rzecz pokrzywdzonego",
    # numer przypisu pdftotext wypisuje osobno — nie stoi przed jego treścią
    P2, "2)",
    "\fDziennik Ustaw", "– 2 –", "Poz. 999",
    "w wysokości do dziesięciu tysięcy złotych.",
    # treść strony kończy się słowem „w”, a przypis 3 zaczyna się od „W brzmieniu…”
    "Art. 3. Latarnik odpowiada za szkodę wyrządzoną z winy umyślnej, chyba że działał na",
    "polecenie organu wskazanego w",
    "\fDziennik Ustaw", "– 3 –", "Poz. 999",
    "§ 7 rozporządzenia.",
    # pdftotext gubi indeks górny: „art. 6¹ ust. 1” → „art. 6 ust. 1”
    "Art. 4.3) Podmioty, o których mowa w art. 6 ust. 1, składają wniosek",
    # przypis 3 przeniesiony na następną stronę
    "3) W brzmieniu ustalonym przez art. 7 ustawy o latarniach",
    "\fDziennik Ustaw", "– 4 –", "Poz. 999",
    "do ministra.",
    "Art. 5.4) Ustawa wdraża przepisy Unii Europejskiej o latarniach morskich i bojach wymienione",
    "morskich, która weszła w życie z dniem 1 marca 2020 r.",
    # przypis wieloakapitowy; numery wyliczenia osobno od treści
    "4) Niniejsza ustawa wdraża:", "dyrektywę o latarniach;", "dyrektywę o bojach.", "1)", "2)",
    "\fDziennik Ustaw", "– 5 –", "Poz. 999",
    "w odnośniku.",
    A6,
])

bledy = 0


def sprawdz(ok: bool, opis: str) -> None:
    global bledy
    bledy += not ok
    print("ok " if ok else "ZLE", opis)


def jednostka(tekst: str) -> pdf_tj.Jednostka:
    num = tekst.split()[1].rstrip(".")
    return pdf_tj.Jednostka(num, num, pdf_tj._rozdziel_indeksy(tekst), [], None)


def bez(tekst: str, slowo: str) -> str:
    assert f" {slowo} " in tekst
    return tekst.replace(f" {slowo} ", " ", 1)


przypisy = pdf_tj.przypisy_md(MD_PRZYPISY)
sprawdz("dyrektywę o bojach" in przypisy["4"] and przypisy["5"] == "Utracił moc.",
        "przypisy_md: wszystkie akapity przypisu, następny przypis osobno")

raw = pdf_tj._tokeny_pdftotext(WARSTWA)
maska = pdf_tj.wyjasnienia_warstwy(raw, przypisy, POS)
wyjasnione = {raw[i] for i in range(len(raw)) if maska[i]}
tresc = [raw[i] for i in range(len(raw)) if not maska[i] and not raw[i].isdigit()]
sprawdz(sum(1 for i in range(len(raw) - 1) if raw[i] == "dziennik" and maska[i]) == 5,
        "nagłówki 5 stron rozpoznane")
sprawdz({"dodany", "morskich", "bojach"} <= wyjasnione, "przypisy (także przeniesiony i wieloakapitowy) rozpoznane")
k = raw.index("wskazanego")
sprawdz(raw[k + 1] == "w" and not maska[k + 1] and maska[k + 2],
        "„w” kończące treść strony nie jest początkiem przypisu „W brzmieniu…”")
sprawdz(not ({"dodany", "brzmieniu", "dyrektywę", "dziennik"} & set(tresc)),
        "w treści nie zostają słowa przypisów ani nagłówków")


def kontrola(tekst: str) -> bool:
    return pdf_tj.wiernosc_pdftotext(jednostka(tekst), raw, maska).ok


for art in (A1, A2, A3, A4, A5, A6):
    sprawdz(kontrola(art), f"wierny odczyt przechodzi: {art[:40]}…")
# słowa obecne w przypisach aktu — dawniej ich usunięcie przechodziło kontrolę
sprawdz(not kontrola(bez(A1, "grzywny")), "art. 1 bez „grzywny” (słowo z przypisu 2) → odmowa")
sprawdz(not kontrola(bez(A1, "karze")), "art. 1 bez „karze” → odmowa")
sprawdz(not kontrola(bez(A2, "nawiązkę")), "art. 2 bez „nawiązkę” → odmowa")
sprawdz(not kontrola(bez(A2, "dziesięciu")), "art. 2 bez słowa za przypisem i nagłówkiem → odmowa")
sprawdz(not kontrola(bez(A3, "w")), "art. 3 bez „w” tuż przed końcem strony → odmowa")
sprawdz(not kontrola(bez(A5, "wdraża")), "art. 5 bez „wdraża” (słowo z przypisu 4) → odmowa")
sprawdz(not kontrola(bez(A6, "maluje")), "art. 6 bez „maluje” → odmowa")
sprawdz(not kontrola(A6.replace("pięć lat", "lat pięć")), "art. 6 z przestawionymi słowami → odmowa")
sprawdz(not kontrola(A6.replace("ołowiu", "kadmu")), "art. 6 z zamienionym słowem → odmowa")

# _dopasuj: indeks zgubiony przez warstwę nie dopasowuje się do „1” z „ust. 1”
md_tok = pdf_tj.tokeny(pdf_tj._rozdziel_indeksy("mowa w art. 6¹ ust. 1, składają"), opcjonalne=True)
sprawdz(pdf_tj._dopasuj(md_tok, pdf_tj.tokeny("mowa w art. 6 ust. 1, składają"), 0, 50) is not None,
        "_dopasuj: „art. 6¹ ust. 1” wobec warstwy „art. 6 ust. 1”")
sprawdz(pdf_tj._dopasuj(md_tok, pdf_tj.tokeny("mowa w art. 6 1 ust. 1, składają"), 0, 50) is not None,
        "_dopasuj: indeks obecny w warstwie jako osobne słowo")

try:
    pdf_tj.wiernosc_pdftotext(jednostka(A1), raw, {"dziennik", "ustaw"})
    sprawdz(False, "stary zbiór słów zamiast maski — brak błędu")
except TypeError:
    sprawdz(True, "stary zbiór słów zamiast maski → TypeError (nie cicha zgoda)")

print("\nwszystko OK" if not bledy else f"\nbłędów: {bledy}")
sys.exit(1 if bledy else 0)
