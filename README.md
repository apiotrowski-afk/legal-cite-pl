# legal-cite

**Legal citation verifier (PL / EU law) — an MCP server that fetches the exact, in-force wording of a cited article straight from the official source.** An anti-hallucination tool for Claude (and any MCP client): instead of trusting the model's memory of a statute, it returns the verbatim text of the cited article from the official register.

**Weryfikator cytatów prawnych (prawo PL / UE) — serwer MCP pobierający dokładne, aktualne brzmienie cytowanego artykułu prosto z oficjalnego źródła.** Narzędzie anti-halucynacyjne dla Claude (i dowolnego klienta MCP).

- 🇵🇱 **PL law** — `api.sejm.gov.pl` (ELI). Returns the **consolidated text** (*tekst jednolity*, currently in force), not the original as-promulgated version.
- 🇪🇺 **EU law** — EUR-Lex (Polish text). *Note: EUR-Lex sometimes serves a bot-challenge (HTTP 202) → returns an error instead of text.*

Returns **only the cited article** (not the whole act). The quote comes straight from the source.

---

## English

### Tools
- `verify_article("art. 45 u.k.k.")` — the wording of a provision. Format: `art. N [ust. M] CODE`.
  Handles letter suffixes (`art. 36a`), `§` as a unit (`art. 58 § 2 KC`), superscripts (`art. 385¹` / `385[1]`).
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
  --memory=256Mi --cpu=1 --max-instances=2 --port=8080
```
Public, no-auth is safe here — the service serves **only public legal texts** (no data, no database, no LLM calls).

Connect in Claude: **Connectors → Add custom connector** → `https://<service-url>.run.app/mcp` (`streamable-http` mounts MCP at `/mcp`).

### Add a new act
Add an entry to `PL_ACTS` (key = abbreviation; `pub`/`year`/`pos` from the Journal of Laws / ELI) or `EU_ACTS` (key = abbreviation, `celex`) in `legal_cite/core.py`.

---

## Polski

### Narzędzia
- `verify_article("art. 45 u.k.k.")` — brzmienie przepisu. Format: `art. N [ust. M] KOD`.
  Obsługuje sufiks literowy (`art. 36a`), § jako jednostkę (`art. 58 § 2 KC`), indeks górny (`art. 385¹` / `385[1]`).
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
  --memory=256Mi --cpu=1 --max-instances=2 --port=8080
```
Publiczny bez auth jest tu bezpieczny — serwis serwuje **wyłącznie publiczne teksty aktów** (zero danych, zero bazy, zero wywołań LLM).

Podłączenie w Claude: **Connectors → Add custom connector** → `https://<adres-serwisu>.run.app/mcp`.

---

## Related / Powiązane
Komplementarny skill do redakcji i analizy umów: **[commercial-legal-pl](https://github.com/apiotrowski-afk/commercial-legal-pl)** — używa `verify_article`, by cytować przepisy ze źródła zamiast z pamięci modelu.

## License
Apache License 2.0 — see [LICENSE](LICENSE).
