FROM python:3.12-slim

# poppler-utils: pdftotext — drugi, niezależny czytnik warstwy tekstowej PDF,
# którym narzędzie sprawdza odczyt tekstów jednolitych dostępnych tylko w PDF
RUN apt-get update && apt-get install -y --no-install-recommends poppler-utils git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml ./
COPY legal_cite ./legal_cite
RUN pip install --no-cache-dir ".[gcs]"

# Konwersje PDF (do ~1,5 min dla k.p.c.) są trzymane tutaj między wywołaniami
ENV LEGAL_CITE_CACHE=/tmp/legal-cite
# Cloud Run wstrzykuje PORT; serwer wykrywa go i wstaje na streamable-http (/mcp)
ENV PORT=8080
EXPOSE 8080
CMD ["legal-cite"]
