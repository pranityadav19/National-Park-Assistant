# National Park Assistant

RAG-style assistant for U.S. national parks with multi-source grounding:
- NPS API: https://developer.nps.gov/api/v1/parks
- NPS park pages: https://www.nps.gov
- NPS developer docs: https://www.nps.gov/subjects/developer/api-documentation.htm
- Wikivoyage: https://en.wikivoyage.org

## Architecture

```text
Next.js UI --> FastAPI /ask --> retrieve park + source chunks --> grounded answer + citations
             FastAPI ingestion endpoints --> NPS API / NPS scrape / Docs scrape / Wikivoyage scrape --> SQLite/Postgres
```

## Quickstart

```bash
cd National-Park-Assistant
docker-compose up --build
```

## Manual backend run

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --reload --port 8000
```

## Manual frontend run

```bash
cd frontend
npm install
cp .env.example .env.local
npm run dev
```

## Ingestion sequence

```bash
curl -X POST http://localhost:8000/ingest/nps-api
curl -X POST http://localhost:8000/ingest/nps-site
curl -X POST http://localhost:8000/ingest/nps-docs
curl -X POST http://localhost:8000/ingest/wikivoyage
```

## Ask

```bash
curl -X POST http://localhost:8000/ask \
  -H "Content-Type: application/json" \
  -d '{"question":"How much does it cost to go to Yellowstone?","park_name":"Yellowstone"}'
```

## Notes
- Official NPS API/site data is prioritized for factual fields (fees/hours/status).
- Wikivoyage is supplemental for season/travel context.
- Responses include source citations and confidence notes.
