FROM python:3.12-slim

WORKDIR /app
COPY pyproject.toml ./
COPY legal_cite ./legal_cite
RUN pip install --no-cache-dir .

# Cloud Run wstrzykuje PORT; serwer wykrywa go i wstaje na streamable-http (/mcp)
ENV PORT=8080
EXPOSE 8080
CMD ["legal-cite"]
