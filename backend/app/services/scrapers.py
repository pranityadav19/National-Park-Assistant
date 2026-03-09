from __future__ import annotations

from datetime import datetime
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup

from app.core.config import settings
from app.services.json_store import JSONStore
from app.utils.text import normalize_whitespace


class BaseScraper:
    async def fetch(self, url: str) -> str:
        headers = {"User-Agent": settings.user_agent}
        async with httpx.AsyncClient(timeout=settings.request_timeout_seconds, headers=headers, follow_redirects=True) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            return resp.text


class NPSSiteScraper(BaseScraper):
    async def ingest(self, limit: int = 10) -> int:
        store = JSONStore()
        data = store.load()
        parks = data.get("parks", [])[:limit]
        count = 0

        for park in parks:
            urls = []
            if park.get("url"):
                urls.append(park["url"])
            code = (park.get("park_code") or "").lower()
            if code:
                urls.append(f"https://www.nps.gov/{code}/index.htm")

            html = None
            resolved_url = None
            for candidate in urls:
                try:
                    html = await self.fetch(candidate)
                    resolved_url = candidate
                    break
                except httpx.HTTPError:
                    continue

            if not html or not resolved_url:
                continue

            soup = BeautifulSoup(html, "lxml")
            paragraphs = [normalize_whitespace(p.get_text(" ")) for p in soup.select("main p")][:20]
            text = "\n".join([p for p in paragraphs if p])[:6000]
            if not text:
                continue

            store.add_source_chunk(
                {
                    "park_code": park.get("park_code"),
                    "source_type": "nps_site",
                    "source_url": resolved_url,
                    "section": "main_content",
                    "content": text,
                    "fetched_at": datetime.utcnow().isoformat(),
                }
            )
            count += 1

        return count


class NPSDocsScraper(BaseScraper):
    DOCS_URL = "https://www.nps.gov/subjects/developer/api-documentation.htm"

    async def ingest(self) -> int:
        try:
            html = await self.fetch(self.DOCS_URL)
        except httpx.HTTPError:
            return 0

        soup = BeautifulSoup(html, "lxml")
        headings = [normalize_whitespace(h.get_text(" ")) for h in soup.select("h1, h2, h3")][:30]
        links = [urljoin(self.DOCS_URL, a.get("href", "")) for a in soup.select("a[href]")][:50]
        content = normalize_whitespace(" | ".join(headings + links))[:7000]
        if not content:
            return 0

        store = JSONStore()
        store.add_source_chunk(
            {
                "park_code": None,
                "source_type": "nps_docs",
                "source_url": self.DOCS_URL,
                "section": "documentation",
                "content": content,
                "fetched_at": datetime.utcnow().isoformat(),
            }
        )
        return 1


class WikivoyageScraper(BaseScraper):
    BASE = "https://en.wikivoyage.org/wiki/"

    async def ingest(self, limit: int = 10) -> int:
        store = JSONStore()
        data = store.load()
        parks = data.get("parks", [])[:limit]
        count = 0

        for park in parks:
            name = park.get("full_name")
            if not name:
                continue
            slug = name.replace(" ", "_")
            url = f"{self.BASE}{slug}"
            try:
                html = await self.fetch(url)
            except httpx.HTTPError:
                continue

            soup = BeautifulSoup(html, "lxml")
            sections = []
            for header in soup.select("h2, h3")[:20]:
                title = normalize_whitespace(header.get_text(" ")).lower()
                if any(k in title for k in ["climate", "best time", "understand", "get in", "see", "do"]):
                    sections.append(title)

            body = [normalize_whitespace(p.get_text(" ")) for p in soup.select("p")[:30]]
            content = normalize_whitespace(" | ".join(sections + body))[:7000]
            if not content:
                continue

            store.add_source_chunk(
                {
                    "park_code": park.get("park_code"),
                    "source_type": "wikivoyage",
                    "source_url": url,
                    "section": "travel_context",
                    "content": content,
                    "fetched_at": datetime.utcnow().isoformat(),
                }
            )
            count += 1

        return count
