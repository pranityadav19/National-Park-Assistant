from fastapi import APIRouter, Query

from app.schemas.park import AskRequest, AskResponse
from app.services.json_store import JSONStore
from app.services.nps_api_ingestor import NPSAPIIngestor
from app.services.qa import QAService
from app.services.scrapers import NPSDocsScraper, NPSSiteScraper, WikivoyageScraper

router = APIRouter()


@router.get("/health")
def health() -> dict:
    return {"status": "ok"}


@router.get("/parks")
def list_parks(query: str | None = Query(default=None)):
    parks = JSONStore().load().get("parks", [])
    if query:
        q = query.lower()
        parks = [p for p in parks if q in (p.get("full_name") or "").lower()]
    return parks[:50]


@router.get("/parks/{park_code}")
def get_park(park_code: str):
    parks = JSONStore().load().get("parks", [])
    park = next((p for p in parks if (p.get("park_code") or "").lower() == park_code.lower()), None)
    return park or {"park_code": park_code, "full_name": "Not found"}


@router.post("/ask", response_model=AskResponse)
def ask(req: AskRequest):
    return QAService().ask(req.question, req.park_code, req.park_name)


@router.post("/ingest/nps-api")
async def ingest_nps_api(limit: int = 200):
    return await NPSAPIIngestor().ingest(limit=limit)


@router.post("/ingest/nps-site")
async def ingest_nps_site(limit: int = 10):
    count = await NPSSiteScraper().ingest(limit=limit)
    return {"ingested": count, "source": "https://www.nps.gov"}


@router.post("/ingest/nps-docs")
async def ingest_nps_docs():
    count = await NPSDocsScraper().ingest()
    return {"ingested": count, "source": "https://www.nps.gov/subjects/developer/api-documentation.htm"}


@router.post("/ingest/wikivoyage")
async def ingest_wikivoyage(limit: int = 10):
    count = await WikivoyageScraper().ingest(limit=limit)
    return {"ingested": count, "source": "https://en.wikivoyage.org"}
