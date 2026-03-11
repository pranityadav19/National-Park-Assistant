from fastapi import APIRouter, Query
import httpx

from app.schemas.park import AskRequest, AskResponse
from app.services.json_store import JSONStore
from app.services.nps_api_ingestor import NPSAPIIngestor, NPS_BASE
from app.services.qa import QAService
from app.services.scrapers import NPSDocsScraper, NPSSiteScraper, WikivoyageScraper
from app.core.config import settings

router = APIRouter()

_photos_cache: list[dict] | None = None

FEATURED_PARK_CODES = [
    "yell", "yose", "grca", "zion", "acad", "ever",
    "glac", "romo", "shen", "olym", "grte", "seki",
    "arch", "brca", "cany", "dena", "havo", "jotr",
]


@router.get("/health")
def health() -> dict:
    return {"status": "ok"}


@router.get("/parks")
def list_parks(query: str | None = Query(default=None)):
    parks = JSONStore().load().get("parks", [])
    if query:
        q = query.lower()
        parks = [p for p in parks if q in (p.get("full_name") or "").lower() or q in (p.get("states") or "").lower()]
    return parks


@router.get("/parks/photos")
async def park_photos():
    global _photos_cache
    if _photos_cache is not None:
        return _photos_cache

    codes = ",".join(FEATURED_PARK_CODES)
    headers = {"X-Api-Key": settings.nps_api_key} if settings.nps_api_key else {}
    photos: list[dict] = []
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(
                f"{NPS_BASE}/parks?parkCode={codes}&limit=50",
                headers=headers,
            )
            resp.raise_for_status()
            for park in resp.json().get("data", []):
                images = park.get("images", [])
                if images:
                    photos.append({
                        "park_code": park.get("parkCode", ""),
                        "full_name": park.get("fullName", ""),
                        "url": images[0].get("url", ""),
                        "alt": images[0].get("altText", park.get("fullName", "")),
                    })
    except Exception:
        pass

    _photos_cache = photos
    return photos


@router.get("/parks/{park_code}")
def get_park(park_code: str):
    parks = JSONStore().load().get("parks", [])
    park = next((p for p in parks if (p.get("park_code") or "").lower() == park_code.lower()), None)
    return park or {"park_code": park_code, "full_name": "Not found"}


@router.post("/ask", response_model=AskResponse)
def ask(req: AskRequest):
    return QAService().ask(req.question, req.park_code, req.park_name)


@router.post("/ingest/nps-api")
async def ingest_nps_api():
    return await NPSAPIIngestor().ingest()


@router.post("/ingest/nps-site")
async def ingest_nps_site(limit: int | None = None):
    count = await NPSSiteScraper().ingest(limit=limit)
    return {"ingested": count, "source": "https://www.nps.gov"}


@router.post("/ingest/wikivoyage")
async def ingest_wikivoyage(limit: int | None = None):
    count = await WikivoyageScraper().ingest(limit=limit)
    return {"ingested": count, "source": "https://en.wikivoyage.org"}


@router.post("/ingest/nps-docs")
async def ingest_nps_docs():
    count = await NPSDocsScraper().ingest()
    return {"ingested": count, "source": "https://www.nps.gov/subjects/developer/api-documentation.htm"}


@router.post("/ingest/all")
async def ingest_all():
    """Run full ingestion pipeline: NPS API → NPS site scraper → Wikivoyage."""
    api_result = await NPSAPIIngestor().ingest()
    site_count = await NPSSiteScraper().ingest()
    wiki_count = await WikivoyageScraper().ingest()
    return {
        "nps_api": api_result,
        "nps_site_chunks": site_count,
        "wikivoyage_chunks": wiki_count,
    }
