# legal-cite

**Legal citation verifier (PL / EU law) — an MCP server that fetches the exact, in-force wording of a cited article straight from the official source.** An anti-hallucination tool for Claude (and any MCP client): instead of trusting the model's memory of a statute, it returns the verbatim text of the cited article from the official register.

**Weryfikator cytatów prawnych (prawo PL / UE) — serwer MCP pobierający dokładne, aktualne brzmienie cytowanego artykułu prosto z oficjalnego źródła.** Narzędzie anti-halucynacyjne dla Claude (i dowolnego klienta MCP).

- 🇵🇱 **PL law** — `api.sejm.gov.pl` (ELI). Returns the **consolidated text** (*tekst jednolity*, currently in force), not the original as-promulgated version.
- 🇪🇺 **EU law** — Publications Office CELLAR / EUR-Lex (Polish text), **latest in-force consolidated version** (CELEX `0…-YYYYMMDD`, found via the CELLAR SPARQL endpoint), not the original Official Journal text — so amendments (e.g. AI Act art. 111(4) added by Regulation 2026/1744) are not missed. Consolidated text is labelled unofficial (📄), names the amending act behind each changed article and lists amending acts that entered into force after the consolidation date. Amendment markers (►M1, ▼B) are stripped from the quote. Falls back to the original text, with an explicit note, when no consolidated version exists or SPARQL is down.

Returns **only the cited article** (not the whole act). The quote comes straight from the source.

### Consolidated texts available only as PDF (since 2025)

Since 2025 the Sejm ELI API publishes Journal of Laws acts **only as PDF** — the newest consolidated texts of the Civil Code, Labour Code, Civil Procedure Code and others have no HTML. The tool therefore picks the **version first, the format second**: the newest consolidated text is the basis, and when it exists only as PDF, the tool converts the official PDF itself with a **pinned** version of [eli2md](https://github.com/PolskiAgentW/eli2md) (MIT) and reads the article from the resulting tree of units. Such a result is an **unofficial reading of an official PDF** and is labelled as such (📄 instead of 📜), with the Journal of Laws number, link to the PDF, PDF checksum and converter version. Two separate judgements are reported: **fidelity** of the reading and **currency** of the law.

Fidelity checks before anything is returned (any failure → the tool refuses instead of returning an older text):
1. **structure** — article numbers increase in document order; the article is a unit of the tree, not a quoted passage;
2. **text layer, second reader** — the article's words must appear in order in the PDF text layer read by poppler's `pdftotext` (eli2md reads through pdfminer), and words the converter skipped inside the article may only be page headers and footnotes;
3. **older consolidated text in HTML** (official and independent of the PDF) — an identical article is returned **as the official HTML text**, confirmed as unchanged by the newest consolidated text; a different article must be explained by a footnote at the unit or by an amendment that entered into force between the two texts.

Currency is a separate line: the amending acts (Journal of Laws number and date, from the ELI register) that entered into force after the consolidated text's date, or none — and, separately, amending acts already published but not yet in force (with their date). The `[dla modelu]` fields `nowelizacje_po_tj` and `nowelizacje_oczekujace` list their ELI ids. The trailing `[dla modelu]` line carries the same judgements as fields for an LLM reading the tool output.

Measured on 2026-10-10 (8 acts whose newest consolidated text is PDF-only, 4676 articles): 99.7 % pass the text-layer check; of those also present in the older HTML, 4339 are word-for-word identical. Requirements: `pdftotext` (Debian/Ubuntu: `apt install poppler-utils`); without it the PDF path refuses. First conversion of a code takes 30–90 s and is cached on disk (`LEGAL_CITE_CACHE`, default under the system temp dir). Optionally set `LEGAL_CITE_GCS_BUCKET` (and install `.[gcs]`) to keep conversions in Cloud Storage: a new instance downloads them instead of converting (file names carry the PDF checksum and converter version; fidelity checks run on the downloaded file as on a fresh one; any bucket error falls back to conversion). On Cloud Run use at least `--memory=512Mi` and the default request timeout (300 s).

---

## English

### Tools
- `verify_article("art. 45 u.k.k.")` — the wording of a provision. Format: `art. N [ust. M] CODE`.
  Handles letter suffixes (`art. 36a`), `§` as a unit (`art. 58 § 2 KC`), superscript paragraphs (`art. 98 § 1¹ k.p.c.` / `§ 1[1]`), superscripts with letters (`art. 385¹` / `385[1]` / `131¹ᵃ` / `131[1a]`), dotted codes (`k.p.c.`).
  When a consolidated text prints **two wordings of the same paragraph/point** (current one and one entering into force later), the tool returns only the one in force today, chosen by the date in the footnote, and says so; if the date cannot be read, it refuses.
- `list_acts()` — list of supported act codes (PL + EU).

### Run locally (stdio — Claude Desktop / Claude Code)
```bash
pip install -e .
legal-cite          # stdio
```
`claude_desktop_config.json`:
```json
{ "mcpServers": { "legal-cite": { "command": "legal-cite" } } }
```

### Deploy to Cloud Run (streamable-http — one shared URL)
```bash
gcloud run deploy legal-cite \
  --source=. \
  --region=europe-west4 \
  --allow-unauthenticated \
  --memory=512Mi --cpu=1 --max-instances=1 --timeout=300 --port=8080
```
Public, no-auth is safe here — the service serves **only public legal texts** (no data, no database, no LLM calls).

Connect in Claude: **Connectors → Add custom connector** → `https://<service-url>.run.app/mcp` (`streamable-http` mounts MCP at `/mcp`).

### Add a new act
Add an entry to `PL_ACTS` (key = abbreviation; `pub`/`year`/`pos` from the Journal of Laws / ELI) or `EU_ACTS` (key = abbreviation, `celex`) in `legal_cite/core.py`.

---

## Polski

### Prawo UE
Akty UE są cytowane z **najnowszej obowiązującej wersji skonsolidowanej** (CELEX `0…-RRRRMMDD`, ustalanej przez SPARQL CELLAR), a nie z tekstu pierwotnego z Dz.U. UE — inaczej umykają zmiany (np. art. 111 ust. 4 AI Act dodany rozporządzeniem 2026/1744). Tekst skonsolidowany jest oznaczony jako nieurzędowy (📄), z aktem zmieniającym dany artykuł i aktami zmieniającymi, które weszły w życie po dacie konsolidacji. Znaczniki ►M1/▼B są usuwane z cytatu. Gdy wersji skonsolidowanej nie ma albo SPARQL nie odpowiada — tekst pierwotny z jawną adnotacją.

### Narzędzia
- `verify_article("art. 45 u.k.k.")` — brzmienie przepisu. Format: `art. N [ust. M] KOD`.
  Obsługuje sufiks literowy (`art. 36a`), § jako jednostkę (`art. 58 § 2 KC`), paragraf z indeksem górnym (`art. 98 § 1¹ k.p.c.` / `§ 1[1]`), indeks górny z literą (`art. 385¹` / `385[1]` / `131¹ᵃ` / `131[1a]`), kody z kropkami (`k.p.c.`, `k.r.o.`).
  Gdy tekst jednolity drukuje **dwa brzmienia tego samego paragrafu, ustępu lub punktu** (obowiązujące i wchodzące w życie później), narzędzie zwraca tylko obowiązujące dziś — wybrane po dacie z odnośnika — i to zaznacza; gdy daty nie da się odczytać, odmawia.

### Teksty jednolite dostępne tylko w PDF (od 2025 r.)

Od 2025 r. API ELI Sejmu publikuje akty Dziennika Ustaw **wyłącznie w PDF** — najnowsze teksty jednolite k.c., k.p., k.p.c. i innych nie mają HTML. Narzędzie wybiera więc **najpierw wersję, potem format**: podstawą jest najnowszy tekst jednolity, a gdy jest tylko w PDF, narzędzie samo konwertuje urzędowy PDF **przypiętą** wersją [eli2md](https://github.com/PolskiAgentW/eli2md) (MIT) i wycina artykuł z drzewa jednostek. Taki wynik to **nieurzędowy odczyt urzędowego PDF** i tak jest oznaczony (📄 zamiast 📜): numer Dz.U., link do PDF, suma kontrolna PDF, wersja konwertera. Osobno podawane są dwie oceny: **wierność odczytu** i **aktualność prawna**.

Kontrole wierności przed oddaniem wyniku (każda niezaliczona → odmowa zamiast starszego brzmienia):
1. **struktura** — numery artykułów rosną w kolejności dokumentu, artykuł jest węzłem drzewa, nie cytatem w przepisie przejściowym;
2. **warstwa tekstowa, drugi czytnik** — słowa artykułu muszą wystąpić w tej kolejności w warstwie tekstowej PDF czytanej przez `pdftotext` (poppler; eli2md czyta przez pdfminer), a słowa pominięte przez konwerter w obrębie artykułu mogą być tylko nagłówkami stron i przypisami;
3. **starszy tekst jednolity w HTML** (urzędowy, niezależny od PDF) — artykuł identyczny jest zwracany **jako tekst urzędowy HTML**, potwierdzony przez najnowszy t.j. jako niezmieniony; artykuł różny musi mieć wytłumaczenie w odnośniku przy jednostce albo w nowelizacji, która weszła w życie między datami obu tekstów.

Aktualność to osobna linia: akty zmieniające (numer Dz.U. i data, wg wykazu ELI), które weszły w życie po dacie tekstu jednolitego, albo że żaden — i osobno akty ogłoszone, które jeszcze nie obowiązują (z datą). Pola `nowelizacje_po_tj` i `nowelizacje_oczekujace` w linii `[dla modelu]` podają ich identyfikatory ELI. Linia `[dla modelu]` na końcu powtarza te oceny jako pola dla modelu czytającego wynik narzędzia.

Pomiar 2026-10-10 (8 aktów z najnowszym t.j. tylko w PDF, 4676 artykułów): 99,7 % przechodzi kontrolę warstwy tekstowej; spośród obecnych w starszym HTML 4339 jest identycznych co do słowa. Wymagania: `pdftotext` (Debian/Ubuntu: `apt install poppler-utils`); bez niego ścieżka PDF odmawia. Pierwsza konwersja kodeksu trwa 30–90 s i jest trzymana na dysku (`LEGAL_CITE_CACHE`, domyślnie w katalogu tymczasowym systemu). Opcjonalnie `LEGAL_CITE_GCS_BUCKET` (instalacja `.[gcs]`) trzyma konwersje w Cloud Storage: nowa instancja pobiera je zamiast konwertować (nazwa pliku zawiera sumę PDF i wersję konwertera; kontrole wierności biegną na pobranym pliku tak samo; błąd zasobnika = powrót do konwersji). Na Cloud Run co najmniej `--memory=512Mi`.
- `list_acts()` — lista obsługiwanych kodów aktów (PL + UE).

### Uruchomienie lokalne (stdio — Claude Desktop / Claude Code)
```bash
pip install -e .
legal-cite          # stdio
```
Wpis w `claude_desktop_config.json`:
```json
{ "mcpServers": { "legal-cite": { "command": "legal-cite" } } }
```

### Deploy na Cloud Run (streamable-http — współdzielony URL)
```bash
gcloud run deploy legal-cite \
  --source=. \
  --region=europe-west4 \
  --allow-unauthenticated \
  --memory=512Mi --cpu=1 --max-instances=1 --timeout=300 --port=8080
```
Publiczny bez auth jest tu bezpieczny — serwis serwuje **wyłącznie publiczne teksty aktów** (zero danych, zero bazy, zero wywołań LLM).

Podłączenie w Claude: **Connectors → Add custom connector** → `https://<adres-serwisu>.run.app/mcp`.

---

## Ekosystem / Related

Część zestawu otwartych narzędzi LegalTech (PL):
- **[legal-cite-pl](https://github.com/apiotrowski-afk/legal-cite-pl)** — *(ten projekt)* MCP: weryfikacja brzmienia przepisu PL/UE ze źródła.
- **[commercial-legal-pl](https://github.com/apiotrowski-afk/commercial-legal-pl)** — Claude skill: redakcja i analiza umów (PL); używa `verify_article`.
- **[anon-legal-pl](https://github.com/apiotrowski-afk/anon-legal-pl)** — lokalna anonimizacja akt prawnych (PL).
- **[kancelaria-dms](https://github.com/apiotrowski-afk/kancelaria-dms)** — DMS/CRM dla kancelarii (Google Workspace).

## License
Apache License 2.0 — see [LICENSE](LICENSE).
