"""Brzmienie przepisu PL na wskazany dzień (verify_article z na_dzien).

Podstawą jest tekst jednolity ogłoszony najpóźniej w tym dniu ("przed") i
pierwszy ogłoszony po nim ("po"). Teksty jednolite zamrażają stan prawny na
dzień obwieszczenia, a wykaz aktów zmieniających w API ELI podaje daty wejścia
w życie nowelizacji. Brzmienie jest POTWIERDZONE tylko wtedy, gdy wynika z dat
i porównania tekstów:

1. między tekstem "przed" a wskazanym dniem nie weszła w życie żadna
   nowelizacja ustawy → brzmienie z "przed";
2. artykuł brzmi tak samo w "przed" i "po" → to brzmienie (nowelizacje z tego
   okresu go nie zmieniły);
3. wszystkie nowelizacje z okresu między "przed" a "po" weszły w życie najpóźniej
   we wskazanym dniu → brzmienie z "po".

W pozostałych przypadkach narzędzie podaje oba brzmienia i nowelizacje z
datami. Wzmianka o artykule w treści nowelizacji („art. 118 otrzymuje
brzmienie”) jest tylko wskazówką: zmiana może też dotknąć artykułu pośrednio
(„uchyla się rozdział 3”), więc brak wzmianki nigdy nie znaczy „bez zmian”.
Gdy wszystkie nowelizacje wymieniające artykuł leżą po jednej stronie dnia,
podajemy brzmienie z tej strony jako USTALONE Z TREŚCI NOWELIZACJI — słabiej
niż potwierdzone i tak opisane.
"""
from __future__ import annotations

import asyncio
import datetime as _dt
import html as _html
import logging
import re
import subprocess
import time

import httpx

from legal_cite import core

logger = logging.getLogger(__name__)

BASE = "https://api.sejm.gov.pl/eli/acts"
_TTL = 6 * 3600
_akty: dict[str, tuple[float, dict]] = {}       # ident → (czas, metadane)
_html_tj: dict[str, str] = {}                   # ident → surowy HTML tekstu
_segmenty: dict[tuple[str, str], str | None] = {}  # (nowelizacja, akt) → fragment zmieniający akt


def _adres(ident: str) -> str:
    pub, year, pos = ident.split("/")
    return f"{'Dz.U.' if pub == 'DU' else 'M.P.'} {year} poz. {pos}"


def _data(s: str | None) -> _dt.date | None:
    try:
        return _dt.date.fromisoformat((s or "")[:10])
    except ValueError:
        return None


async def _meta(c: httpx.AsyncClient, ident: str) -> dict:
    hit = _akty.get(ident)
    if hit and time.monotonic() - hit[0] < _TTL:
        return hit[1]
    meta = (await c.get(f"{BASE}/{ident}")).json()
    _akty[ident] = (time.monotonic(), meta)
    return meta


async def _teksty(c: httpx.AsyncClient, info: dict) -> tuple[dict, list[dict]]:
    """Metadane ustawy i wszystkie jej teksty jednolite z tekstem (HTML albo PDF),
    od najstarszego. Pierwotny tekst ustawy stoi na początku jako stan z dnia
    wejścia w życie."""
    ident = f"{info['pub']}/{info['year']}/{info['pos']}"
    meta = await _meta(c, ident)
    out = []
    if meta.get("textHTML"):
        out.append({"id": ident, "data": _data(meta.get("entryIntoForce") or meta.get("promulgation")),
                    "html": True, "pdf": False, "meta": meta, "pierwotny": True})
    for ent in (meta.get("references") or {}).get("Inf. o tekście jednolitym", []):
        tj_id = ent.get("id") or ""
        if tj_id.count("/") != 2:
            continue
        m = await _meta(c, tj_id)
        data = _data(m.get("announcementDate"))
        # obwieszczenie bywa w rejestrze, zanim API ma jego pliki (k.k. 2026/1342)
        pdf = bool(m.get("textPDF") and m.get("texts"))
        if data and (m.get("textHTML") or pdf):
            out.append({"id": tj_id, "data": data, "html": bool(m.get("textHTML")), "pdf": pdf,
                        "meta": m, "pierwotny": False})
    out.sort(key=lambda w: w["data"] or _dt.date.min)
    return meta, out


async def _artykul(c: httpx.AsyncClient, info: dict, wpis: dict, art: str,
                   dzien: _dt.date) -> tuple[str, str | None]:
    """(stan, tekst) artykułu w danym tekście na dany dzień. stan: 'ok', 'brak'
    (artykułu nie ma), 'nie_obowiazuje' (wydrukowany z wyprzedzeniem),
    'niejednoznaczne', 'blad'."""
    klucz = core._kanon_art(art)
    token = core._NA_DZIEN.set(dzien)
    try:
        if wpis["html"]:
            ident = wpis["id"]
            if ident not in _html_tj:
                r = await c.get(f"{BASE}/{ident}/text.html")
                if r.status_code != 200:
                    return "blad", f"HTTP {r.status_code}"
                _html_tj[ident] = r.text
            key = f"{core._klucz_pl(info)}@{ident}@{dzien}"
            raw = _html_tj[ident]
            try:
                tekst = core.extract_pl_article_html(key, raw, art, None)
            except core.JeszczeNieObowiazuje as e:
                return "nie_obowiazuje", f"{e.data:%d.%m.%Y}"
            except core.Niejednoznaczne as e:
                return "niejednoznaczne", str(e)
            if tekst:
                return "ok", tekst
            jednostki = core._jednostki_html(key, raw)
            if any(n == klucz for n, *_ in jednostki):
                return "blad", "nie udało się wyciąć artykułu"
            # artykuł bez własnego znacznika (art. 15 u.ś.u.d.e. stoi w bloku art. 14)
            # albo starszy HTML bez znaczników: wycinek po nagłówku „Art. N.”, jak w core
            tekst = core.extract_pl_article(core._strip_html(raw), art, None)
            if tekst:
                return "ok", tekst
            return ("brak", None) if jednostki else ("blad", "tekst bez znaczników jednostek")
        from legal_cite import pdf_tj
        if not pdf_tj.konwerter_dostepny():
            return "blad", "brak konwertera PDF"
        od = await pdf_tj.odczyt(wpis["id"], wpis["meta"])
        jednostki, _ = pdf_tj.jednostki_md(od.md, od.przypisy, dzien)
        trafienia = [j for j in jednostki if j.klucz == klucz]
        if not trafienia:
            return "brak", None
        wybor, nieznane = core._wybierz_brzmienie([j.data for j in trafienia], dzien)
        jedn = trafienia[wybor]
        if core._jeszcze_nie(od.przypisy, jedn.wlasny_odnosnik, dzien):
            return "nie_obowiazuje", None
        if jedn.niejednoznaczne or nieznane:
            return "niejednoznaczne", "; ".join(jedn.uwagi)
        if not od.raw_tok or not pdf_tj.wiernosc_pdftotext(jedn, od.raw_tok, od.wyjasnienia).ok:
            return "blad", "odczyt PDF nie przeszedł kontroli warstwy tekstowej"
        return "ok", jedn.czysty()
    except httpx.HTTPError as e:
        return "blad", type(e).__name__
    finally:
        core._NA_DZIEN.reset(token)


def _segment(tekst_html: str, data_ustawy: str) -> str | None:
    """Część nowelizacji zmieniająca naszą ustawę: od „W ustawie z dnia …” do
    następnego artykułu nowelizacji."""
    tekst = re.sub(r'<(script|style)\b[^>]*>.*?</\1>', ' ', tekst_html, flags=re.I | re.S)
    tekst = re.sub(r'\s+', ' ', _html.unescape(re.sub(r'<[^>]+>', ' ', tekst)))
    m = re.search(r'[Ww] ustawie z dnia ' + re.escape(data_ustawy), tekst)
    if not m:
        return None
    koniec = re.search(r'Art\.\s*\d+[a-z]*\.\s+(?:W\s+ustawie|Do\s|Przepis|Ustawa\s+wchodzi|Traci\s+moc)',
                       tekst[m.end():])
    return tekst[m.start():m.end() + (koniec.start() if koniec else len(tekst))]


def _numer(art: str) -> str | None:
    """Wzorzec numeru artykułu w tekście nowelizacji: „118”, „36a”, a dla
    117¹ / 117[1] także „117 1” (indeks górny po zdjęciu znaczników HTML)."""
    nr = re.match(r'\d+', art)
    if not nr:
        return None
    rest = re.sub(r'[\[\]()^\s]', '', art[nr.end():])
    if not rest:
        return rf'{nr.group()}(?![\d\w¹²³⁴⁵⁶⁷⁸⁹⁰])(?!\s\d)'
    sup = rest.translate(str.maketrans("0123456789", "⁰¹²³⁴⁵⁶⁷⁸⁹"))
    return rf'{nr.group()}\s*(?:{re.escape(rest)}|{re.escape(sup)})(?![\d\w])'


def _wymienia(segment: str, art: str) -> bool:
    numer = _numer(art)
    if not numer:
        return False
    if re.search(rf'(?<![\w.])art\.\s*{numer}', segment, re.I):
        return True
    if not re.fullmatch(r'\d+', art):
        return False
    n = int(art)
    return any(int(a) <= n <= int(b) for a, b in re.findall(r'art\.\s*(\d+)\s*[–-]\s*(\d+)', segment))


def _uchyla(segment: str, art: str, rozdzial: str | None) -> bool:
    """Czy nowelizacja wprost uchyla artykuł: „uchyla się art. 14”, „art. 14
    uchyla się”, „uchyla się art. 12–15”, „uchyla się rozdział 3”."""
    numer = _numer(art)
    if numer and re.search(rf'uchyla\s+się\s+art\.\s*{numer}|(?<![\w.])art\.\s*{numer}\s+uchyla\s+się', segment):
        return True
    if re.fullmatch(r'\d+', art) and any(
            int(a) <= int(art) <= int(b)
            for a, b in re.findall(r'uchyla\s+się\s+art\.\s*(\d+)\s*[–-]\s*(\d+)', segment)):
        return True
    return bool(rozdzial and re.search(rf'uchyla\s+się\s+rozdział\s+{re.escape(rozdzial)}(?![\d\w])', segment))


def _nowe_brzmienie(segment: str, art: str) -> str | None:
    """Całe nowe brzmienie artykułu nadane nowelizacją („art. 118 otrzymuje
    brzmienie: „Art. 118. …”", „dodaje się art. 117¹ w brzmieniu: „…”") —
    tekst w cudzysłowie, z zagnieżdżonymi cudzysłowami w środku."""
    numer = _numer(art)
    if not numer:
        return None
    m = re.search(rf'(?<![\w.])art\.\s*{numer}\s+otrzymuje\s+brzmienie\s*:?\s*„', segment) or \
        re.search(rf'dodaje\s+się\s+art\.\s*{numer}\s+w\s+brzmieniu\s*:?\s*„', segment)
    if not m:
        return None
    glebokosc, i = 1, m.end()
    while i < len(segment) and glebokosc:
        glebokosc += {"„": 1, "”": -1}.get(segment[i], 0)
        i += 1
    return segment[m.end():i - 1] if glebokosc == 0 else None


async def _tekst_nowelizacji(c: httpx.AsyncClient, ident: str) -> str | None:
    """Treść nowelizacji: HTML, a gdy API daje tylko PDF (Dz.U. od 2025 r.) —
    warstwa tekstowa PDF przez pdftotext."""
    m = await _meta(c, ident)
    if m.get("textHTML"):
        r = await c.get(f"{BASE}/{ident}/text.html")
        return r.text if r.status_code == 200 else None
    if not (m.get("textPDF") and m.get("texts")):
        return None
    from legal_cite import pdf_tj
    pdf_tj.CACHE_DIR.mkdir(parents=True, exist_ok=True)
    pdf = pdf_tj.CACHE_DIR / f"nowelizacja_{ident.replace('/', '_')}.pdf"
    if not pdf.exists():
        r = await c.get(f"{BASE}/{ident}/text.pdf")
        if r.status_code != 200 or not r.content.startswith(b"%PDF"):
            return None
        pdf.write_bytes(r.content)
    return await asyncio.to_thread(pdf_tj._warstwa, pdf, pdf.with_suffix(".txt"))


def _rozdzial(raw_html: str, art: str) -> str | None:
    """Numer rozdziału, w którym stoi artykuł (wg znaczników HTML tekstu)."""
    klucz = core._kanon_art(art)
    poz = raw_html.find(f'data-id="arti_{klucz}"') if klucz else -1
    if poz < 0 and klucz and re.search(r'_\d+[a-z]+$', klucz):  # t.j. 2024: „arti_131_1_a”
        poz = raw_html.find('data-id="arti_' + re.sub(r'_(\d+)([a-z]+)$', r'_\1_\2', klucz) + '"')
    if poz < 0 and klucz and klucz.isdigit():  # artykuł bez własnego znacznika: nagłówek w tekście
        m = re.search(rf'Art\.(?:\s|&nbsp;)*{klucz}\s*\.', raw_html)
        poz = m.start() if m else -1
    if poz < 0:
        return None
    for m in re.finditer(r'<div class="unit unit_chpt[^"]*" id="[^"]*" data-id="chpt_([^"]+)"', raw_html):
        if m.start() < poz < core._koniec_div(raw_html, m.start()):
            return m.group(1).replace("_", "")
    return None


async def _nowelizacje(c: httpx.AsyncClient, meta: dict, od: _dt.date, do: _dt.date,
                       art: str, sprawdzaj: bool, rozdzial: str | None = None) -> list[dict]:
    """Nowelizacje ustawy wchodzące w życie w (od, do], z datą i — gdy sprawdzaj —
    informacją, czy wymieniają artykuł albo jego rozdział (None = nie dało się
    sprawdzić)."""
    data_ustawy = re.search(r'z dnia (\d{1,2} \w+ \d{4} r\.)', meta.get("title") or "")
    out = []
    wpisy = [(ent, _data(ent.get("date"))) for ent in (meta.get("references") or {}).get("Akty zmieniające", [])]
    wpisy = [(ent, d) for ent, d in wpisy if d and od < d <= do]
    sprawdzaj = sprawdzaj and len(wpisy) <= 20  # przy setkach nowelizacji (stan sprzed t.j.) nie pobieramy każdej
    for ent, d in wpisy:
        poz = {"id": ent["id"], "data": d, "wymienia": None, "nowe_brzmienie": None, "uchyla": False}
        if sprawdzaj and data_ustawy:
            kl = (ent["id"], meta.get("ELI") or "")
            if kl not in _segmenty:
                _segmenty[kl] = None
                try:
                    tekst = await _tekst_nowelizacji(c, ent["id"])
                    if tekst:
                        _segmenty[kl] = _segment(tekst, data_ustawy.group(1))
                except (httpx.HTTPError, OSError, subprocess.SubprocessError) as e:
                    logger.warning("nowelizacja %s blad=%s", ent["id"], type(e).__name__)
            seg = _segmenty[kl]
            if seg is not None:
                poz["wymienia"] = _wymienia(seg, art) or bool(
                    rozdzial and re.search(rf'(?i)rozdzia\w*\s+{re.escape(rozdzial)}(?![\d\w])', seg))
                poz["nowe_brzmienie"] = _nowe_brzmienie(seg, art)
                poz["uchyla"] = _uchyla(seg, art, rozdzial)
        out.append(poz)
    return sorted(out, key=lambda p: p["data"])


def _opis_nowelizacji(lista: list[dict], art: str, rozdzial: str | None = None) -> str:
    if not lista:
        return ""
    wiersze = []
    for p in lista[:15]:
        w = {True: f"wymienia art. {art}" + (f" lub jego rozdział {rozdzial}" if rozdzial else ""),
             False: f"nie wymienia art. {art} wprost",
             None: "treści nie sprawdzono"}[p["wymienia"]]
        if p.get("uchyla"):
            w = f"UCHYLA art. {art}" + (f" (uchyla rozdział {rozdzial})" if rozdzial else "")
        wiersze.append(f"- {_adres(p['id'])}, wejście w życie {p['data']:%d.%m.%Y} ({w})")
    if len(lista) > 15:
        wiersze.append(f"- … i {len(lista) - 15} kolejnych")
    wiersze.append("Daty to wejście w życie całej nowelizacji; pojedyncze jej przepisy mogą wchodzić w życie później.")
    return "\n".join(wiersze)


def _zrodlo(wpis: dict) -> str:
    adres = wpis["meta"].get("displayAddress") or _adres(wpis["id"])
    if wpis["pierwotny"]:
        return f"tekst pierwotny ustawy ({adres}, HTML)"
    rodzaj = "tekst urzędowy HTML" if wpis["html"] else "NIEURZĘDOWY odczyt urzędowego PDF"
    return f"t.j. {adres} z {wpis['data']:%d.%m.%Y}, {rodzaj}"


def _taki_sam(a: str, b: str) -> bool:
    from legal_cite import pdf_tj
    return "".join(pdf_tj.tokeny(a)) == "".join(pdf_tj.tokeny(b))


async def verify_article_na_dzien(citation: str, na_dzien: str) -> str:
    dzien = _data(na_dzien)
    if not dzien:
        return f"❌ Nierozpoznana data: '{na_dzien}'. Użyj formatu RRRR-MM-DD, np. 2018-07-01."
    # Na dzień zwracamy zawsze cały artykuł, więc jednostkę odcinamy przed
    # parsowaniem (parser nie zna jednostek z indeksem górnym: „§ 1¹”).
    jednostka = re.search(r'\s(?:ust\.|§+|pkt|lit\.)\s*\S+(?:\s(?:pkt|lit\.)\s*\S+)*', citation)
    parsed = core.parse_citation(citation[:jednostka.start()] + citation[jednostka.end():]
                                 if jednostka else citation)
    if not parsed:
        return (f"❌ Nierozpoznany format: '{citation}'\nUżyj: 'art. N [ust. M] KOD' — np. "
                f"'art. 118 KC'.\nLista kodów: list_acts().")
    act, art = parsed["act"], parsed["art"]
    ustep = jednostka.group().strip() if jednostka else None
    if core._resolve(act, core.EU_ACTS):
        return ("❌ Brzmienie na dzień jest dostępne tylko dla aktów polskich; dla aktów UE "
                "narzędzie podaje wyłącznie aktualną wersję skonsolidowaną.")
    pl_key = core._resolve(act, core.PL_ACTS)
    if not pl_key:
        known = ", ".join(core.PL_ACTS)
        return f"❌ Nieznany kod aktu: '{act}'\nObsługiwane: {known}"
    info = core.PL_ACTS[pl_key]
    ref = f"art. {art}"
    nazwa = info["name"]
    naglowek_dnia = f"brzmienie na dzień {dzien:%d.%m.%Y}"
    uwaga_jedn = (f"\n(zapytano o {ref} {ustep} — podaję cały artykuł; wskaż jednostkę z treści)"
                  if ustep else "")

    async with httpx.AsyncClient(follow_redirects=True, timeout=60, headers=core._HEADERS) as c:
        try:
            meta, teksty = await _teksty(c, info)
        except (httpx.HTTPError, ValueError) as e:
            return f"❌ Nie udało się pobrać metadanych {nazwa} z api.sejm.gov.pl ({type(e).__name__})"
        wejscie = _data(meta.get("entryIntoForce"))
        if wejscie and dzien < wejscie:
            return (f"❌ {nazwa} weszła w życie {wejscie:%d.%m.%Y}; w dniu {dzien:%d.%m.%Y} "
                    f"jeszcze nie obowiązywała.")
        przed = [w for w in teksty if w["data"] and w["data"] <= dzien]
        po = [w for w in teksty if w["data"] and w["data"] > dzien]
        if not przed:
            return (f"❌ {ref} {nazwa}, {naglowek_dnia}: brak czytelnego tekstu jednolitego z tego "
                    f"okresu w API ELI, więc brzmienia nie ustalam.")

        # najbliższy czytelny tekst przed dniem
        baza = stan_b = tekst_b = None
        for wpis in reversed(przed):
            stan_b, tekst_b = await _artykul(c, info, wpis, art, dzien)
            if stan_b != "blad":
                baza = wpis
                break
        if baza is None:
            return (f"❌ {ref} {nazwa}, {naglowek_dnia}: nie udało się odczytać tekstu "
                    f"jednolitego sprzed tego dnia ({tekst_b}).")
        nast = stan_n = tekst_n = None
        for wpis in po:
            stan_n, tekst_n = await _artykul(c, info, wpis, art, dzien)
            if stan_n != "blad":
                nast = wpis
                break

        dzis = _dt.date.today()
        przyszly = dzien > dzis
        okno_do = nast["data"] if nast else dzien
        rozdzial = _rozdzial(_html_tj.get(baza["id"], ""), art) if baza["html"] else None
        lista = await _nowelizacje(c, meta, baza["data"], max(okno_do, dzien), art, sprawdzaj=True,
                                   rozdzial=rozdzial)
        # na dziś i na przyszłość: zmiany już ogłoszone, które wejdą w życie później
        zapowiedzi = (await _nowelizacje(c, meta, max(okno_do, dzien), _dt.date.max, art, sprawdzaj=True,
                                         rozdzial=rozdzial) if dzien >= dzis else [])
    zapowiedziane_uchylenie = next((p for p in zapowiedzi if p["uchyla"]), None)
    do_dnia = [p for p in lista if p["data"] <= dzien]
    po_dniu = [p for p in lista if p["data"] > dzien]

    def wynik(ustalenie: str, kod: str, wpis: dict, stan: str, tekst: str | None, dodatek: str = "") -> str:
        # o stanie w danym dniu mówimy wprost tylko przy ustaleniu, nie przy „nieustalone”
        pewne = kod != "nieustalone"
        if stan == "brak":
            tresc = f"W tym tekście nie ma {ref}" + (
                f" — w dniu {dzien:%d.%m.%Y} artykuł nie istniał." if pewne else ".")
        elif stan == "nie_obowiazuje":
            tresc = (f"Tekst drukuje {ref} z wyprzedzeniem"
                     + (f" (wchodzi w życie {tekst})" if tekst else "")
                     + (f" — w dniu {dzien:%d.%m.%Y} jeszcze nie obowiązywał." if pewne else "."))
        elif stan == "niejednoznaczne":
            tresc = f"Tekst drukuje kilka brzmień i z odnośników nie da się ustalić, które obowiązywało ({tekst})."
        else:
            tresc = tekst or ""
        znak = "📜" if wpis["html"] else "📄"
        nowele = _opis_nowelizacji(lista, art, rozdzial)
        return (f"{znak} **{nazwa}**, {ref} — {naglowek_dnia}{uwaga_jedn}\n"
                f"(źródło: api.sejm.gov.pl, {_zrodlo(wpis)})\n"
                f"Ustalenie: {ustalenie}"
                + ("\nUwaga: data jest w przyszłości — brzmienie wg zmian już ogłoszonych." if przyszly else "")
                + f"\n\n{tresc}{dodatek}"
                + (f"\n\nNowelizacje ustawy wchodzące w życie od {baza['data']:%d.%m.%Y} do "
                   f"{max(okno_do, dzien):%d.%m.%Y} (wg wykazu API ELI):\n{nowele}" if nowele else "")
                + (f"\n\nOgłoszone zmiany wchodzące w życie po {max(okno_do, dzien):%d.%m.%Y}:\n"
                   f"{_opis_nowelizacji(zapowiedzi, art, rozdzial)}" if zapowiedzi else "")
                + (f"\n\n⚠ {_adres(zapowiedziane_uchylenie['id'])} uchyla {ref} z dniem "
                   f"{zapowiedziane_uchylenie['data']:%d.%m.%Y}." if zapowiedziane_uchylenie else "")
                + f"\n\n[dla modelu] na_dzien={dzien.isoformat()}; ustalenie={kod}; "
                + (f"uchylenie_od={zapowiedziane_uchylenie['data'].isoformat()}; " if zapowiedziane_uchylenie else "")
                + f"cytuj_jako=„{ref} {nazwa} w brzmieniu na dzień {dzien:%d.%m.%Y}, {_zrodlo(wpis)}”")

    if not do_dnia:
        return wynik(f"potwierdzone — od daty tego tekstu ({baza['data']:%d.%m.%Y}) do "
                     f"{dzien:%d.%m.%Y} nie weszła w życie żadna nowelizacja ustawy.",
                     "potwierdzone_brak_nowelizacji", baza, stan_b, tekst_b)
    if nast and stan_b == stan_n == "ok" and _taki_sam(tekst_b, tekst_n):
        return wynik(f"potwierdzone — artykuł brzmi tak samo w tym tekście i w kolejnym "
                     f"({_zrodlo(nast)}); nowelizacje z tego okresu go nie zmieniły.",
                     "potwierdzone_identyczne_w_kolejnym_tj", baza, stan_b, tekst_b)
    if nast and stan_b == stan_n and stan_b in ("brak", "nie_obowiazuje"):
        return wynik(f"potwierdzone — artykułu nie ma ani w tym tekście, ani w kolejnym "
                     f"({_zrodlo(nast)}).", "potwierdzone_brak_artykulu", baza, stan_b, tekst_b)
    if nast and not po_dniu:
        return wynik(f"potwierdzone — wszystkie nowelizacje z okresu między tekstami jednolitymi "
                     f"weszły w życie najpóźniej {dzien:%d.%m.%Y}, a kolejny tekst je uwzględnia.",
                     "potwierdzone_kolejny_tj", nast, stan_n, tekst_n)

    uchylenie = next((p for p in do_dnia if p["uchyla"]), None)
    if uchylenie:
        return wynik(f"ustalone z treści nowelizacji — {_adres(uchylenie['id'])}, która weszła w życie "
                     f"{uchylenie['data']:%d.%m.%Y}, uchyla {ref}"
                     + (f" (uchyla rozdział {rozdzial})" if rozdzial else "")
                     + f", więc w dniu {dzien:%d.%m.%Y} artykuł nie obowiązuje. Poniżej brzmienie sprzed "
                     "uchylenia.", "ustalone_uchylony", baza, stan_b, tekst_b)

    wymieniajace = [p for p in lista if p["wymienia"]]
    ostatnia = wymieniajace[-1] if wymieniajace else None
    if (nast and stan_n == "ok" and ostatnia and all(p["data"] <= dzien for p in wymieniajace)
            and ostatnia["nowe_brzmienie"] and _taki_sam(ostatnia["nowe_brzmienie"], tekst_n)):
        return wynik(f"potwierdzone — {_adres(ostatnia['id'])} (w życie {ostatnia['data']:%d.%m.%Y}, przed tym "
                     f"dniem) nadała {ref} całe nowe brzmienie, a kolejny tekst ({_zrodlo(nast)}) ma to samo "
                     "brzmienie, więc późniejsze nowelizacje artykułu nie zmieniły.",
                     "potwierdzone_brzmieniem_z_nowelizacji", nast, stan_n, tekst_n)
    if nast and wymieniajace and all(p["data"] <= dzien for p in wymieniajace):
        return wynik("ustalone z treści nowelizacji (nie potwierdzone) — nowelizacje wymieniające "
                     f"{ref} weszły w życie przed tym dniem, więc podaję brzmienie z kolejnego tekstu. "
                     "Zmiana mogła też dotknąć artykułu pośrednio — sprawdź wykaz poniżej.",
                     "ustalone_z_tresci_nowelizacji", nast, stan_n, tekst_n)
    if wymieniajace and all(p["data"] > dzien for p in wymieniajace):
        return wynik("ustalone z treści nowelizacji (nie potwierdzone) — nowelizacje wymieniające "
                     f"{ref} weszły w życie dopiero po tym dniu, więc podaję brzmienie sprzed nich. "
                     "Zmiana mogła też dotknąć artykułu pośrednio — sprawdź wykaz poniżej.",
                     "ustalone_z_tresci_nowelizacji", baza, stan_b, tekst_b)

    dodatek = ""
    if nast:
        druga = {"ok": tekst_n, "brak": f"(w tym tekście nie ma {ref})",
                 "nie_obowiazuje": "(artykuł wydrukowany z wyprzedzeniem)"}.get(stan_n, f"({tekst_n})")
        dodatek = f"\n\nBrzmienie w kolejnym tekście ({_zrodlo(nast)}):\n{druga}"
    return wynik(f"nieustalone — między tym tekstem a {dzien:%d.%m.%Y} weszły w życie nowelizacje "
                 "ustawy" + (", a kolejny tekst jednolity ma inne brzmienie" if nast else
                             ", a nowszego tekstu jednolitego jeszcze nie ma")
                 + ". Podaję brzmienie z tekstu przed tym dniem"
                 + (" i z kolejnego" if nast else "") + "; ustal, która nowelizacja zmieniła artykuł.",
                 "nieustalone", baza, stan_b, tekst_b, dodatek)
