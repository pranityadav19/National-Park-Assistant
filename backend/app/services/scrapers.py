from __future__ import annotations

import asyncio
from datetime import datetime

import httpx
from bs4 import BeautifulSoup

from app.core.config import settings
from app.services.json_store import JSONStore
from app.utils.text import normalize_whitespace


class BaseScraper:
    async def fetch(self, url: str) -> str:
        headers = {"User-Agent": settings.user_agent}
        async with httpx.AsyncClient(
            timeout=settings.request_timeout_seconds, headers=headers, follow_redirects=True
        ) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            return resp.text


class NPSSiteScraper(BaseScraper):
    # Subpages to scrape per park (appended to https://www.nps.gov/{code}/)
    SUBPAGES = [
        ("", "main"),
        ("planyourvisit/", "plan_your_visit"),
        ("nature/", "nature"),
        ("historyculture/", "history_culture"),
        ("learn/historyculture/", "history_culture"),
        ("getinvolved/", "get_involved"),
    ]

    async def _scrape_park(self, park: dict) -> list[dict]:
        code = (park.get("park_code") or "").lower()
        if not code:
            return []

        chunks: list[dict] = []
        seen_sections: set[str] = set()

        for subpath, section_name in self.SUBPAGES:
            if section_name in seen_sections:
                continue
            url = f"https://www.nps.gov/{code}/{subpath}"
            try:
                html = await self.fetch(url)
            except httpx.HTTPError:
                continue

            soup = BeautifulSoup(html, "lxml")
            content_parts = []
            # NPS.gov uses .cs_control divs; fall back to role=main or body paragraphs
            selectors = [
                ".cs_control h1, .cs_control h2, .cs_control h3, .cs_control p, .cs_control li",
                "[role='main'] h1, [role='main'] h2, [role='main'] h3, [role='main'] p, [role='main'] li",
                "main h1, main h2, main h3, main p, main li",
                "article h2, article h3, article p, article li",
                ".Component p, .container p",
            ]
            for sel in selectors:
                elems = soup.select(sel)[:60]
                if elems:
                    for elem in elems:
                        text = normalize_whitespace(elem.get_text(" "))
                        if text and len(text) > 20:
                            content_parts.append(text)
                    break

            text = "\n".join(content_parts)[:8000]
            if not text:
                continue

            seen_sections.add(section_name)
            chunks.append({
                "park_code": park.get("park_code"),
                "source_type": "nps_site",
                "source_url": url,
                "section": section_name,
                "content": text,
                "fetched_at": datetime.utcnow().isoformat(),
            })

        return chunks

    async def ingest(self, limit: int | None = None) -> int:
        store = JSONStore()
        data = store.load()
        parks = data.get("parks", [])
        if limit is not None:
            parks = parks[:limit]

        semaphore = asyncio.Semaphore(5)

        async def scrape_with_semaphore(park: dict) -> list[dict]:
            async with semaphore:
                return await self._scrape_park(park)

        results = await asyncio.gather(
            *[scrape_with_semaphore(p) for p in parks], return_exceptions=True
        )

        all_chunks: list[dict] = []
        for result in results:
            if isinstance(result, list):
                all_chunks.extend(result)

        store.clear_source_chunks_by_type("nps_site")
        store.batch_add_source_chunks(all_chunks)
        return len(all_chunks)


class WikivoyageScraper(BaseScraper):
    BASE = "https://en.wikivoyage.org/wiki/"

    async def _scrape_park(self, park: dict) -> dict | None:
        name = park.get("full_name")
        if not name:
            return None

        slug = name.replace(" ", "_")
        url = f"{self.BASE}{slug}"
        try:
            html = await self.fetch(url)
        except httpx.HTTPError:
            return None

        soup = BeautifulSoup(html, "lxml")
        content_parts: list[str] = []
        current_section = "Overview"

        # Wikivoyage: use #mw-content-text which always contains the article body
        # (soup.find(class_="mw-parser-output") returns the wrong element — there are multiple)
        mw_output = soup.find(id="mw-content-text") or soup.body or soup
        for elem in mw_output.find_all(["h2", "h3", "p", "ul"])[:80]:
            if elem.name in ("h2", "h3"):
                current_section = normalize_whitespace(elem.get_text(" "))
            elif elem.name == "p":
                text = normalize_whitespace(elem.get_text(" "))
                if text and len(text) > 20:
                    content_parts.append(f"[{current_section}] {text}")
            elif elem.name == "ul":
                items = [
                    normalize_whitespace(li.get_text(" "))
                    for li in elem.find_all("li")
                    if li.get_text(" ").strip()
                ]
                if items:
                    content_parts.append(f"[{current_section}] " + "; ".join(items[:12]))

        content = "\n".join(content_parts)[:8000]
        if not content:
            return None

        return {
            "park_code": park.get("park_code"),
            "source_type": "wikivoyage",
            "source_url": url,
            "section": "travel_guide",
            "content": content,
            "fetched_at": datetime.utcnow().isoformat(),
        }

    async def ingest(self, limit: int | None = None) -> int:
        store = JSONStore()
        data = store.load()
        parks = data.get("parks", [])
        if limit is not None:
            parks = parks[:limit]

        semaphore = asyncio.Semaphore(5)

        async def scrape_with_semaphore(park: dict) -> dict | None:
            async with semaphore:
                return await self._scrape_park(park)

        results = await asyncio.gather(
            *[scrape_with_semaphore(p) for p in parks], return_exceptions=True
        )

        all_chunks = [r for r in results if isinstance(r, dict)]
        store.clear_source_chunks_by_type("wikivoyage")
        store.batch_add_source_chunks(all_chunks)
        return len(all_chunks)


class NPSDocsScraper(BaseScraper):
    """Retained for API compatibility but no longer called by default."""

    DOCS_URL = "https://www.nps.gov/subjects/developer/api-documentation.htm"

    async def ingest(self) -> int:
        return 0
