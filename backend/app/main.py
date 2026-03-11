from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import router


async def _run_initial_ingest() -> None:
    from app.services.nps_api_ingestor import NPSAPIIngestor
    from app.services.scrapers import NPSSiteScraper, WikivoyageScraper

    print("Starting initial data ingestion from NPS API...")
    try:
        result = await NPSAPIIngestor().ingest()
        print(f"NPS API ingestion complete: {result}")
    except Exception as exc:
        print(f"NPS API ingestion failed: {exc}")

    print("Scraping NPS.gov pages...")
    try:
        count = await NPSSiteScraper().ingest()
        print(f"NPS site scraping complete: {count} chunks")
    except Exception as exc:
        print(f"NPS site scraping failed: {exc}")

    print("Scraping Wikivoyage...")
    try:
        count = await WikivoyageScraper().ingest()
        print(f"Wikivoyage scraping complete: {count} chunks")
    except Exception as exc:
        print(f"Wikivoyage scraping failed: {exc}")

    print("Initial ingestion finished.")


@asynccontextmanager
async def lifespan(app: FastAPI):
    import asyncio
    from app.services.json_store import JSONStore

    data = JSONStore().load()
    if not data.get("parks"):
        asyncio.create_task(_run_initial_ingest())

    yield


app = FastAPI(title="National Parks Assistant API", version="0.3.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:3001",
        "http://127.0.0.1:3001",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)
