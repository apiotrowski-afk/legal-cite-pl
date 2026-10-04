"""Odczyt daty wejścia w życie z odnośnika — bez sieci, w sekundę.

To najmłodsza i najbardziej krucha część wycinania: od tej daty zależy, KTÓRE
brzmienie artykułu zwracamy, gdy tekst jednolity drukuje ich kilka. Dwa
pozostałe walidatory wymagają sieci i kilku minut, ten chodzi od razu.

    python testy/daty.py
"""
import datetime as dt
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from legal_cite import core

MAPA = {
    # realne odnośniki z t.j. k.p.c. (DU/2024/1568) i u.ś.u.d.e. (DU/2024/1513)
    '3': 'Ze zmianą wprowadzoną przez art. 26 pkt 1 lit. a ustawy z dnia 12 lipca '
         '2024 r. - Przepisy wprowadzające ustawę - Prawo komunikacji elektronicznej '
         '(Dz. U. poz. 1222), która wejdzie w życie z dniem 10 listopada 2024 r.',
    '7': 'W brzmieniu ustalonym przez art. 26 pkt 2 ustawy, o której mowa w odnośniku 3.',
    '9': 'Przez art. 26 pkt 3 ustawy, o której mowa w odnośniku 3.',
    '8': 'Obowiązuje do wejścia w życie zmiany, o której mowa w odnośniku 9.',
    '67': 'Obowiązuje do wejścia w życie zmiany, o której mowa w odnośniku 68.',
    '68': 'Przez art. 2 pkt 2 ustawy z dnia 5 sierpnia 2015 r. o zmianie ustawy o '
          'ochronie konkurencji i konsumentów oraz niektórych innych ustaw (Dz. U. '
          'poz. 1634); wejdzie w życie z dniem 18 kwietnia 2026 r.',
    '76': 'W tym brzmieniu obowiązuje do wejścia w życie zmiany, o której mowa w odnośniku 77.',
    '77': 'Ze zmianą wprowadzoną przez art. 2 pkt 1 ustawy, o której mowa w odnośniku 71.',
    '71': 'Tytuł działu ze zmianą wprowadzoną przez art. 2 pkt 1 ustawy z dnia 12 lipca '
          '2024 r. (Dz. U. poz. 1222), która wejdzie w życie z dniem 10 listopada 2024 r.',
    # łańcuch dłuższy niż dopuszczony (ochrona przed pętlą i przed zgadywaniem)
    'a': 'o której mowa w odnośniku b', 'b': 'o której mowa w odnośniku c',
    'c': 'o której mowa w odnośniku d', 'd': 'o której mowa w odnośniku e',
    'e': 'wejdzie w życie z dniem 1 marca 2027 r.',
    # pętla
    'x': 'o której mowa w odnośniku y', 'y': 'o której mowa w odnośniku x',
    # wszystkie nazwy miesięcy w dopełniaczu
    **{str(100 + i): f'wejdzie w życie z dniem 5 {m} 2026 r.' for i, m in enumerate(
        ['stycznia', 'lutego', 'marca', 'kwietnia', 'maja', 'czerwca', 'lipca',
         'sierpnia', 'września', 'października', 'listopada', 'grudnia'])},
}

PRZYPADKI = [
    ('68', dt.date(2026, 4, 18), 'data wprost w odnośniku'),
    ('7', dt.date(2024, 11, 10), 'odesłanie o jeden krok'),
    ('9', dt.date(2024, 11, 10), 'odesłanie o jeden krok, inna formuła'),
    ('77', dt.date(2024, 11, 10), 'odesłanie o dwa kroki'),
    ('67', None, '„obowiązuje DO wejścia w życie" to koniec, nie początek'),
    ('8', None, 'to samo, bez „w tym brzmieniu"'),
    ('76', None, 'to samo, z „w tym brzmieniu"'),
    ('a', None, 'łańcuch dłuższy niż 3 kroki — wolimy nie zgadywać'),
    ('x', None, 'pętla odesłań nie zawiesza odczytu'),
    ('999', None, 'odnośnik, którego nie ma'),
]
PRZYPADKI += [(str(100 + i), dt.date(2026, i + 1, 5), f'miesiąc {i + 1}')
              for i in range(12)]

bledy = 0
for nr, oczekiwana, opis in PRZYPADKI:
    wynik = core._data_wejscia(MAPA, nr)
    status = 'ok ' if wynik == oczekiwana else 'ZLE'
    if wynik != oczekiwana:
        bledy += 1
    print(f'{status} odnośnik {nr:4s} → {str(wynik):12s} (oczekiwano {oczekiwana}) — {opis}')

print(f'\n{len(PRZYPADKI) - bledy}/{len(PRZYPADKI)} przypadków OK')
sys.exit(1 if bledy else 0)
