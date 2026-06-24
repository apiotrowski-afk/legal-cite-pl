# legal-cite

Serwer **MCP** weryfikujący **dokładne, aktualne brzmienie przepisu** prosto z oficjalnego źródła — narzędzie anti-halucynacyjne dla Claude (i dowolnego klienta MCP). Zamiast polegać na pamięci modelu, pobiera tekst zacytowanego artykułu wprost z urzędowego repozytorium.

- **Prawo PL** — `api.sejm.gov.pl` (ELI). Zwraca **tekst jednolity** (aktualny), nie pierwotny z dnia ogłoszenia.
- **Prawo UE** — EUR-Lex (tekst polski). *Uwaga: EUR-Lex bywa za bot-challenge (HTTP 202) — wtedy zwraca błąd zamiast tekstu.*

Zwraca **tylko zacytowany artykuł** (nie cały akt). Cytat wprost ze źródła.

## Narzędzia
- `verify_article("art. 45 u.k.k.")` — brzmienie przepisu. Format: `art. N [ust. M] KOD`.
  Obsługuje sufiks literowy (`art. 36a`), § jako jednostkę (`art. 58 § 2 KC`), indeks górny (`art. 385¹` / `385[1]`).
- `list_acts()` — lista obsługiwanych kodów aktów (PL + UE).

## Uruchomienie lokalne (stdio — Claude Desktop / Claude Code)
```bash
pip install -e .
legal-cite          # stdio
```
Wpis w `claude_desktop_config.json`:
```json
{ "mcpServers": { "legal-cite": { "command": "legal-cite" } } }
```

## Deploy na Cloud Run (streamable-http — współdzielony URL)
```bash
gcloud run deploy legal-cite \
  --source=. \
  --region=europe-west4 \
  --allow-unauthenticated \
  --memory=256Mi --cpu=1 --max-instances=2 --port=8080
```
Publiczny bez auth jest bezpieczny — serwis serwuje **wyłącznie publiczne teksty aktów prawnych** (zero danych, zero bazy, zero wywołań LLM).

### Podłączenie w Claude (custom connector)
Connectors → **Add custom connector** → URL:
```
https://<adres-serwisu>.run.app/mcp
```
(`streamable-http` montuje MCP pod `/mcp`.)

## Dodanie nowego aktu
Dopisz wpis do `PL_ACTS` (klucz = skrót, `pub`/`year`/`pos` z Dziennika Ustaw — ELI) lub `EU_ACTS` (klucz = skrót, `celex`) w `legal_cite/core.py`.

## Licencja
Apache License 2.0 — zob. [LICENSE](LICENSE).
