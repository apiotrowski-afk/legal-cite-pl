"""Stres-test legal-cite na tysiącach jednostek redakcyjnych, z Astrą jako sędzią.

Wzorzec jest niezależny od ścieżki produkcyjnej: PDF NAJNOWSZEGO tekstu
jednolitego z api.sejm.gov.pl czytany przez `pdftotext -layout` (inny tryb niż
kontrola wierności w pdf_tj) i własne cięcie na artykuły. Cytaty są
budowane tak, jak pisze je prawnik: skrót z słownika, adres Dz.U. tekstu
jednolitego albo aktu pierwotnego, identyfikator ELI; poziomy art. / ust. / § / pkt.

Kroki (każdy wznawialny, wyniki w KATALOG):
    python -I testy/stres_astra.py proba   [N_ustaw_losowych=40] [N_rozporz=10] [jednostek_na_akt=40] [ziarno=2026]
    python -I testy/stres_astra.py uruchom [rownolegle=4]      # verify_article lokalnie
    python -I testy/stres_astra.py porownaj                    # deterministycznie z PDF
    python -I testy/stres_astra.py astra   [rownolegle=4] [kontrola=0.1]  # gpt-6-astra przez Codex
    python -I testy/stres_astra.py raport

Do Astry trafia wyłącznie tekst publicznych aktów prawnych (bez danych klientów).
"""
import asyncio, collections, json, os, pathlib, random, re, subprocess, sys, tempfile
import urllib.parse, urllib.request

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from legal_cite import core, pdf_tj

KATALOG = pathlib.Path(os.environ.get("STRES_KATALOG", pathlib.Path.home() / "legal-cite-stres"))
KATALOG.mkdir(parents=True, exist_ok=True)
PDF_DIR = KATALOG / "pdf"; PDF_DIR.mkdir(exist_ok=True)
PROBA = KATALOG / "proba.jsonl"
WYNIKI = KATALOG / "wyniki.jsonl"
POROWNANIE = KATALOG / "porownanie.jsonl"
OCENY = KATALOG / "oceny_astra.jsonl"
BASE = "https://api.sejm.gov.pl/eli/acts"
UA = {"User-Agent": "legal-cite-stres/0.1 (+https://github.com/apiotrowski-afk/legal-cite-pl)"}


def _json(url):
    req = urllib.request.Request(url, headers=UA)
    return json.load(urllib.request.urlopen(req, timeout=60))


def _czytaj(path):
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()] if path.exists() else []


# --- wzorzec: PDF najnowszego t.j. -----------------------------------------

def _najnowszy_tj(pub, year, pos):
    """Identyfikator najnowszego t.j. (albo aktu pierwotnego) i jego metadane."""
    meta = _json(f"{BASE}/{pub}/{year}/{pos}")
    ids = []
    for ent in (meta.get("references") or {}).get("Inf. o tekście jednolitym", []):
        p = (ent.get("id") or "").split("/")
        if len(p) == 3 and p[1].isdigit() and p[2].isdigit():
            ids.append(p)
    if ids:
        p = max(ids, key=lambda x: (int(x[1]), int(x[2])))
        return "/".join(p), _json(f"{BASE}/{'/'.join(p)}"), meta
    return f"{pub}/{year}/{pos}", meta, meta


def _tekst_pdf(ident):
    plik = PDF_DIR / (ident.replace("/", "_") + ".txt")
    if plik.exists():
        return plik.read_text(encoding="utf-8")
    pdf = PDF_DIR / (ident.replace("/", "_") + ".pdf")
    if not pdf.exists():
        req = urllib.request.Request(f"{BASE}/{ident}/text.pdf", headers=UA)
        dane = urllib.request.urlopen(req, timeout=120).read()
        if not dane.startswith(b"%PDF"):
            raise RuntimeError(f"{ident}: brak PDF")
        pdf.write_bytes(dane)
    subprocess.run(["pdftotext", "-layout", "-enc", "UTF-8", str(pdf), str(plik)],
                   check=True, timeout=180, capture_output=True)
    return plik.read_text(encoding="utf-8")


_NAGLOWEK_STRONY = re.compile(r"(?m)^\s*(©Kancelaria Sejmu|Dziennik Ustaw\s+–\s*\d+\s*–\s*Poz\.|s\. \d+/\d+|\d{4}-\d{2}-\d{2}\s*$).*$")


def _czysc(t):
    return _NAGLOWEK_STRONY.sub("", t)


def artykuly(tekst, glowna="Art."):
    """Lista (numer, start, koniec) artykułów (albo § w rozporządzeniu) w PDF.
    Numer z indeksem górnym w druku 2026 r. ma postać „22[1a]”; w starszych
    drukach pdftotext skleja indeks z numerem („Art. 47961.”) — takie numery
    wypadają przez kontrolę ciągu rosnącego."""
    znak = r"Art\." if glowna == "Art." else "§"
    rx = re.compile(r"(?m)^[ \t]*" + znak + r"[ \t]*(\d+)([a-z]{0,3})(\[\d+[a-z]*\])?\.(?=\s|\d+\))")
    m_all = list(rx.finditer(tekst))
    # początek trzonu: pierwszy „Art. 1.” / „§ 1.” (obwieszczenie przed nim pomijamy)
    start = next((i for i, m in enumerate(m_all) if m.group(1) == "1" and not m.group(2) and not m.group(3)), None)
    if start is None:
        return []
    m_all = m_all[start:]
    out, prev = [], 0
    for i, m in enumerate(m_all):
        n = int(m.group(1))
        nxt = int(m_all[i + 1].group(1)) if i + 1 < len(m_all) else n
        konc = m_all[i + 1].start() if i + 1 < len(m_all) else len(tekst)
        if prev <= n and n - prev <= 30 and (nxt >= n or i + 1 == len(m_all)):
            out.append((m.group(1) + m.group(2) + (m.group(3) or ""), m.start(), konc))
            prev = n
    if out:  # ostatni artykuł: nie dalej niż 20 tys. znaków (załączniki, podpisy)
        n, s, k = out[-1]
        out[-1] = (n, s, min(k, s + 20000))
    seen = collections.Counter(n for n, *_ in out)
    return [x for x in out if seen[x[0]] == 1]


_NUM = r"(\d+[a-z]?(?:\[\d+[a-z]*\])?)"


def podjednostki(seg, glowna):
    """Ustępy / paragrafy / punkty w segmencie artykułu (z PDF), także pierwszy
    w wierszu z numerem artykułu („Art. 2. § 1. …”, „Art. 5. 1. …”)."""
    out = []
    glowa = r"(?:^[ \t]*Art\.[ \t]*\S+?\.(?:\d+\)[ \t]*)*[ \t]*|^[ \t]*)"
    if glowna == "Art.":
        for m in re.finditer(r"(?m)" + glowa + r"§[ \t]*" + _NUM + r"\.[ \t]+\S", seg):
            out.append(("§", m.group(1), m.start()))
        if not out:
            for m in re.finditer(r"(?m)" + glowa + _NUM + r"\.[ \t]+[A-ZĄĆĘŁŃÓŚŹŻ(„]", seg):
                out.append(("ust.", m.group(1), m.start()))
    for m in re.finditer(r"(?m)^[ \t]*" + _NUM + r"\)[ \t]+\S", seg):
        out.append(("pkt", m.group(1), m.start()))
    return out


# --- krok 1: próba ---------------------------------------------------------

def _akty_slownika():
    po_poz, kody = {}, collections.defaultdict(list)
    for k, v in core.PL_ACTS.items():
        if v.get("tekst_u") or v["pub"] != "DU":
            continue
        klucz = (v["pub"], v["year"], v["pos"])
        po_poz.setdefault(klucz, v)
        kody[klucz].append(k)
    return [dict(pub=p, year=y, pos=n, name=v["name"], kody=kody[(p, y, n)], zrodlo="slownik")
            for (p, y, n), v in po_poz.items()]


def _akty_losowe(typ, n, rnd):
    wszystkie, off = [], 0
    while True:
        q = urllib.parse.urlencode({"publisher": "DU", "type": typ, "inForce": "1", "limit": 500, "offset": off})
        it = _json(f"{BASE}/search?{q}").get("items", [])
        wszystkie += it
        if len(it) < 500:
            break
        off += 500
    zle = re.compile(r"o zmianie|zmieniając|o ratyfikacji|budżetow|Przepisy wprowadzające|"
                     r"o uchyleniu|w sprawie (?:ogłoszenia|sprostowania)", re.I)
    kand = [a for a in wszystkie if not zle.search(a.get("title") or "")]
    rnd.shuffle(kand)
    return [dict(pub=a["publisher"], year=a["year"], pos=a["pos"], name=a["title"], kody=[], zrodlo=typ)
            for a in kand[:n]]


def _cytat(akt, adres_tj, adres_pierw, glowna, art, pod, rnd):
    jedn = f"{'art.' if glowna == 'Art.' else '§'} {art}"
    if pod:
        typ, num = pod
        jedn += f" {typ} {num}"
    warianty = []
    if akt["kody"]:
        warianty += [rnd.choice(akt["kody"])] * 3
        kod = rnd.choice(akt["kody"])
        if "." not in kod and kod.isupper() and len(kod) <= 4:
            warianty.append(".".join(kod.lower()) + ".")      # KPC → k.p.c.
    warianty += [adres_tj, adres_pierw, f"{akt['pub']}/{akt['year']}/{akt['pos']}"]
    return f"{jedn} {rnd.choice(warianty)}"


def proba(n_ustaw=40, n_rozp=10, na_akt=40, ziarno=2026):
    rnd = random.Random(ziarno)
    akty = _akty_slownika() + _akty_losowe("Ustawa", n_ustaw, rnd) + _akty_losowe("Rozporządzenie", n_rozp, rnd)
    gotowe = {(r["pub"], r["year"], r["pos"]) for r in _czytaj(PROBA)}
    with PROBA.open("a", encoding="utf-8") as f:
        for akt in akty:
            if (akt["pub"], akt["year"], akt["pos"]) in gotowe:
                continue
            try:
                ident, meta_tj, meta = _najnowszy_tj(akt["pub"], akt["year"], akt["pos"])
                if not meta_tj.get("textPDF"):
                    print("bez PDF:", ident); continue
                tekst = _tekst_pdf(ident)
            except Exception as e:
                print("pominięty", akt["pub"], akt["year"], akt["pos"], type(e).__name__, e); continue
            glowna = "§" if (meta.get("type") == "Rozporządzenie" and not re.search(r"(?m)^\s*Art\. 1\.", tekst)) else "Art."
            arts = artykuly(tekst, glowna)
            if len(arts) < 3:
                print("za mało jednostek:", ident, len(arts)); continue
            adres_tj = meta_tj.get("displayAddress") or ident
            adres_pierw = meta.get("displayAddress") or f"{akt['pub']}/{akt['year']}/{akt['pos']}"
            wyb = rnd.sample(arts, min(na_akt, len(arts)))
            for art, s, k in wyb:
                seg = tekst[s:k]
                pods = podjednostki(seg, glowna)
                pod = None
                r = rnd.random()
                if pods and r < 0.6:
                    ust = [p for p in pods if p[0] != "pkt"]
                    pkt = [p for p in pods if p[0] == "pkt"]
                    if ust and (r < 0.45 or not pkt):
                        pod = rnd.choice(ust)[:2]
                    elif pkt:
                        pk = rnd.choice(pkt)
                        nad = [u for u in ust if u[2] < pk[2]]
                        # punkt cytujemy z ustępem/paragrafem, w którym stoi (jak prawnik)
                        pod = (f"{nad[-1][0]} {nad[-1][1]} pkt", pk[1]) if nad else pk[:2]
                cyt = _cytat(akt, adres_tj, adres_pierw, glowna, art, pod, rnd)
                f.write(json.dumps(dict(id=f"{ident}#{art}#{pod and '_'.join(pod)}", cytat=cyt,
                                        pub=akt["pub"], year=akt["year"], pos=akt["pos"], akt=akt["name"][:200],
                                        zrodlo=akt["zrodlo"], tj=ident, data_tj=meta_tj.get("announcementDate"),
                                        tj_html=bool(meta_tj.get("textHTML")), glowna=glowna, art=art,
                                        pod=pod), ensure_ascii=False) + "\n")
            f.flush()
            print(f"{ident:16} {len(wyb):3} jedn. z {len(arts):4}  {akt['name'][:60]}")
    print("próba:", len(_czytaj(PROBA)), "jednostek")


# --- krok 2: odpowiedzi legal-cite -----------------------------------------

async def uruchom(rownolegle=4):
    proba_ = _czytaj(PROBA)
    gotowe = {r["id"] for r in _czytaj(WYNIKI)}
    todo = [p for p in proba_ if p["id"] not in gotowe]
    # akt po akcie — pamięć podręczna procesu (t.j., PDF) jest wtedy wykorzystywana
    todo.sort(key=lambda p: (p["tj"], p["id"]))
    sem = asyncio.Semaphore(rownolegle)
    f = WYNIKI.open("a", encoding="utf-8")
    licz = collections.Counter()

    async def jeden(p):
        async with sem:
            try:
                odp = await asyncio.wait_for(core.verify_article(p["cytat"]), 600)
            except Exception as e:
                odp = f"!! WYJĄTEK {type(e).__name__}: {e}"
            f.write(json.dumps(dict(id=p["id"], odp=odp), ensure_ascii=False) + "\n"); f.flush()
            licz["ok" if odp.startswith(("📜", "📄")) else "odmowa" if odp.startswith("❌") else "inne"] += 1
            if sum(licz.values()) % 50 == 0:
                print(sum(licz.values()), "/", len(todo), dict(licz), flush=True)

    # grupami po akcie, żeby nie konwertować kilku kodeksów naraz
    po_akcie = collections.defaultdict(list)
    for p in todo:
        po_akcie[p["tj"]].append(p)
    for tj, lista in po_akcie.items():
        await jeden(lista[0])                     # rozgrzewa pamięć podręczną aktu
        await asyncio.gather(*(jeden(p) for p in lista[1:]))
    f.close()
    print("koniec:", dict(licz))


# --- krok 3: porównanie deterministyczne z PDF ------------------------------

def tresc_odpowiedzi(odp):
    """Sam przepis z odpowiedzi legal-cite (bez nagłówka i bloku [dla modelu])."""
    if not odp.startswith(("📜", "📄")):
        return None
    cz = odp.split("\n\n")
    ciało = [c for c in cz[1:] if not c.startswith("[dla modelu]")]
    return "\n\n".join(ciało).strip()


def _w_kolejnosci(a, b):
    """Jaka część słów a występuje w b w tej samej kolejności (LCS / len(a))."""
    if not a:
        return 0.0
    import difflib
    sm = difflib.SequenceMatcher(None, a, b, autojunk=False)
    return sum(bl.size for bl in sm.get_matching_blocks()) / len(a)


def porownaj():
    proba_ = {p["id"]: p for p in _czytaj(PROBA)}
    teksty = {}
    out = POROWNANIE.open("w", encoding="utf-8")
    licz = collections.Counter()
    for w in _czytaj(WYNIKI):
        p = proba_.get(w["id"])
        if not p:
            continue
        if p["tj"] not in teksty:
            teksty[p["tj"]] = _tekst_pdf(p["tj"])
        t = teksty[p["tj"]]
        seg = next((t[s:k] for n, s, k in artykuly(t, p["glowna"]) if n == p["art"]), "")
        seg_tok = pdf_tj._tokeny_pdftotext(_czysc(seg))
        tresc = tresc_odpowiedzi(w["odp"])
        rec = dict(id=w["id"])
        if tresc is None:
            rec["klasa"] = "odmowa" if w["odp"].startswith("❌") else "wyjatek"
        else:
            lc_tok = pdf_tj.tokeny(tresc)
            rec["lc_w_pdf"] = round(_w_kolejnosci(lc_tok, seg_tok), 3)   # czy LC nie dodał/zmienił słów
            rec["pdf_w_lc"] = round(_w_kolejnosci(seg_tok, lc_tok), 3)   # czy LC nie uciął (tylko poziom art.)
            rec["lc_slow"], rec["pdf_slow"] = len(lc_tok), len(seg_tok)
            pelny = not p["pod"]
            if rec["lc_w_pdf"] >= 0.97 and (not pelny or rec["pdf_w_lc"] >= 0.85):
                rec["klasa"] = "zgodne"
            else:
                rec["klasa"] = "rozbiezne"
        licz[rec["klasa"]] += 1
        out.write(json.dumps(rec, ensure_ascii=False) + "\n")
    out.close()
    print(dict(licz))


# --- krok 4: Astra ----------------------------------------------------------

PROMPT = """Jesteś sędzią w teście narzędzia, które zwraca brzmienie polskiego przepisu prawa ze źródła urzędowego.
Dla każdej pozycji dostajesz: cytat (o co pytano), ODPOWIEDŹ narzędzia oraz WZORZEC — tekst całego artykułu
(albo paragrafu rozporządzenia) z PDF najnowszego tekstu jednolitego w Dzienniku Ustaw (warstwa tekstowa pdftotext:
mogą w niej być nagłówki stron, przypisy u dołu strony, numery odnośników, indeksy górne sklejone z numerem, łamane wyrazy —
to szum, nie błąd narzędzia). Narzędzie z zasady pomija „pkt”/„lit.” w cytacie i zwraca cały ustęp/paragraf
(albo cały artykuł, gdy cytat nie wskazuje ustępu/paragrafu) — to jest POPRAWNE, jeśli zwrócona jednostka zawiera
wskazany punkt. „nadmiar” oceniaj tylko względem najmniejszej jednostki, którą narzędzie powinno zwrócić wg tej zasady.
Gdy tekst jednolity drukuje dwa brzmienia (obecne i przyszłe, z odnośnikiem o dacie wejścia w życie), poprawne jest
brzmienie obowiązujące dziś ({dzis}). Odmowa narzędzia (❌) jest poprawna tylko, gdy ma uzasadnienie w źródle
(np. jednostka uchylona/nie istnieje, nie da się ustalić brzmienia) — sama ostrożność bez powodu to błąd „zbędna_odmowa”.

Oceń każdą pozycję. Klasy:
- ok — właściwa jednostka, pełna, wierne brzmienie obowiązujące
- ok_odmowa — odmowa słuszna
- zla_jednostka — inny artykuł/ustęp niż cytowany
- uciete — brakuje części jednostki (zdania, punktów, końca)
- nadmiar — dołączona treść spoza jednostki (sąsiedni ustęp/artykuł, przypisy, nagłówki rozdziałów)
- znieksztalcone — słowa/liczby zmienione względem wzorca
- zle_brzmienie — wzięte brzmienie nieobowiązujące (przyszłe lub dawne)
- zbedna_odmowa — odmowa, choć źródło pozwala podać brzmienie, a narzędzie nie wskazuje rzeczowego powodu
- odmowa_ostrozna — odmowa, bo kontrole odczytu nie przeszły (nieczytelna warstwa PDF, złe kodowanie, przeplot kolumn,
  rozbieżność z inną warstwą); człowiek mógłby odczytać tekst, ale narzędzie z zasady nie zgaduje — NIE jest to błąd
- wzorzec_niepewny — wzorca nie da się użyć (zły fragment PDF), nie oceniaj narzędzia

Odpowiedz WYŁĄCZNIE tablicą JSON, po jednym obiekcie na pozycję, w tej samej kolejności:
[{{"id": "...", "klasa": "...", "pewnosc": "wysoka|srednia|niska", "uzasadnienie": "max 2 zdania, konkret: czego brakuje / co jest nie tak"}}]

POZYCJE:
{pozycje}"""


def _codex(prompt, wysilek="medium"):
    nvm = sorted(pathlib.Path.home().glob(".nvm/versions/node/*/bin"))
    env = dict(os.environ, PATH=f"{nvm[-1]}:{os.environ['PATH']}" if nvm else os.environ["PATH"])
    with tempfile.TemporaryDirectory() as kat:
        wy = pathlib.Path(kat) / "odp.md"
        r = subprocess.run(["codex", "exec", "--ephemeral", "--skip-git-repo-check", "-s", "read-only", "-C", kat,
                            "-m", "gpt-6-astra", "-c", 'web_search="disabled"', "-c", "features.apps=false",
                            "-c", f'model_reasoning_effort="{wysilek}"', "-o", str(wy), "-"],
                           input=prompt, text=True, capture_output=True, timeout=1200, env=env)
        if r.returncode != 0 or not wy.exists():
            raise RuntimeError("codex: " + (r.stderr or "")[-400:])
        return wy.read_text(encoding="utf-8")


def _skroc(s, n):
    return s if len(s) <= n else s[:n] + f"\n[… ucięto {len(s) - n} znaków]"


async def astra(rownolegle=4, kontrola=0.1, partia=6):
    proba_ = {p["id"]: p for p in _czytaj(PROBA)}
    odp = {w["id"]: w["odp"] for w in _czytaj(WYNIKI)}
    por = _czytaj(POROWNANIE)
    ocenione = {o["id"] for o in _czytaj(OCENY)}
    rnd = random.Random(7)
    wybrane = [r for r in por if r["klasa"] != "zgodne" or rnd.random() < kontrola]
    wybrane = [r for r in wybrane if r["id"] not in ocenione]
    print("do oceny Astry:", len(wybrane), collections.Counter(r["klasa"] for r in wybrane))
    teksty = {}

    def pozycja(r):
        p = proba_[r["id"]]
        if p["tj"] not in teksty:
            teksty[p["tj"]] = _tekst_pdf(p["tj"])
        t = teksty[p["tj"]]
        seg = next((t[s:k] for n, s, k in artykuly(t, p["glowna"]) if n == p["art"]), "(nie znaleziono w PDF)")
        return (f"### id: {r['id']}\nCYTAT: {p['cytat']}\nAKT: {p['akt']} (t.j. {p['tj']}, ogłoszony {p['data_tj']})\n"
                f"ODPOWIEDŹ NARZĘDZIA:\n{_skroc(odp[r['id']], 7000)}\n\nWZORZEC (PDF):\n{_skroc(_czysc(seg), 9000)}\n")

    partie = [wybrane[i:i + partia] for i in range(0, len(wybrane), partia)]
    sem = asyncio.Semaphore(rownolegle)
    f = OCENY.open("a", encoding="utf-8")
    import datetime
    dzis = datetime.date.today().isoformat()
    zrobione = 0

    async def jedna(pt):
        nonlocal zrobione
        async with sem:
            prompt = PROMPT.format(dzis=dzis, pozycje="\n".join(pozycja(r) for r in pt))
            for proba_nr in range(3):
                try:
                    tekst = await asyncio.to_thread(_codex, prompt)
                    m = re.search(r"\[.*\]", tekst, re.S)
                    lista = json.loads(m.group(0))
                    break
                except Exception as e:
                    print("astra błąd, ponawiam:", type(e).__name__, str(e)[:200], flush=True)
                    await asyncio.sleep(30 * (proba_nr + 1))
            else:
                return
            ids = {r["id"] for r in pt}
            for o in lista:
                if o.get("id") in ids:
                    o["porownanie"] = next(r for r in pt if r["id"] == o["id"])
                    f.write(json.dumps(o, ensure_ascii=False) + "\n")
            f.flush()
            zrobione += 1
            print(f"partie {zrobione}/{len(partie)}", flush=True)

    await asyncio.gather(*(jedna(pt) for pt in partie))
    f.close()


# --- krok 5: raport ---------------------------------------------------------

def raport():
    proba_ = {p["id"]: p for p in _czytaj(PROBA)}
    por = {r["id"]: r for r in _czytaj(POROWNANIE)}
    oc = {o["id"]: o for o in _czytaj(OCENY)}
    print(f"próba: {len(proba_)} jednostek w {len({p['tj'] for p in proba_.values()})} aktach")
    print("porównanie z PDF:", dict(collections.Counter(r["klasa"] for r in por.values())))
    poziom = collections.Counter((proba_[i]["pod"] or ["art"])[0].split()[-1] for i in por)
    print("poziomy:", dict(poziom))
    print("Astra:", dict(collections.Counter(o["klasa"] for o in oc.values())))
    kontrola = [o for o in oc.values() if o["porownanie"]["klasa"] == "zgodne"]
    print("  w tym kontrola zgodnych:", dict(collections.Counter(o["klasa"] for o in kontrola)))
    bledy = [o for o in oc.values() if o["klasa"] not in ("ok", "ok_odmowa", "odmowa_ostrozna", "wzorzec_niepewny")]
    print("\nBŁĘDY wg Astry:", len(bledy))
    for o in sorted(bledy, key=lambda o: (o["klasa"], o["id"])):
        print(f"- [{o['klasa']}/{o.get('pewnosc')}] {proba_[o['id']]['cytat']} — {o.get('uzasadnienie')}")


if __name__ == "__main__":
    krok = sys.argv[1] if len(sys.argv) > 1 else "raport"
    arg = [float(a) if "." in a else int(a) for a in sys.argv[2:]]
    if krok == "proba":
        proba(*arg)
    elif krok == "uruchom":
        asyncio.run(uruchom(*arg))
    elif krok == "porownaj":
        porownaj()
    elif krok == "astra":
        asyncio.run(astra(*arg))
    else:
        raport()
