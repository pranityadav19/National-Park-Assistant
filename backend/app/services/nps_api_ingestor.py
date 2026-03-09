from __future__ import annotations

from datetime import datetime

import httpx

from app.core.config import settings
from app.services.json_store import JSONStore
from app.utils.text import normalize_whitespace

NPS_API_URL = "https://developer.nps.gov/api/v1/parks"


class NPSAPIIngestor:
    async def ingest(self, limit: int = 200) -> dict:
        headers = {"X-Api-Key": settings.nps_api_key} if settings.nps_api_key else {}
        params = {"limit": limit}

        async with httpx.AsyncClient(timeout=settings.request_timeout_seconds, headers=headers) as client:
            response = await client.get(NPS_API_URL, params=params)
            response.raise_for_status()
            payload = response.json()

        store = JSONStore()
        data = payload.get("data", [])
        upserts = 0
        for item in data:
            park_code = item.get("parkCode")
            if not park_code:
                continue

            fees = item.get("entranceFees", [])
            hours = item.get("operatingHours", [])
            fee_summary = None
            hours_summary = None

            if fees:
                fee_summary = "; ".join(
                    normalize_whitespace(f"{f.get('title', 'Fee')}: ${f.get('cost', 'N/A')} ({f.get('description', '')})")
                    for f in fees[:3]
                )
            if hours:
                first = hours[0]
                hours_summary = normalize_whitespace(f"{first.get('name', 'Hours')}: {first.get('description', '')}")

            park_record = {
                "park_code": park_code,
                "full_name": item.get("fullName") or park_code,
                "states": item.get("states"),
                "description": normalize_whitespace(item.get("description", "")) or None,
                "entrance_fee_summary": fee_summary,
                "operating_hours_summary": hours_summary,
                "weather_info": normalize_whitespace(item.get("weatherInfo", "")) or None,
                "url": item.get("url"),
                "latitude": item.get("latitude"),
                "longitude": item.get("longitude"),
            }

            readable_context = normalize_whitespace(
                " ".join(
                    [
                        f"{park_record['full_name']} ({park_record.get('states') or 'N/A'})",
                        park_record.get("description") or "",
                        f"Fees: {fee_summary}" if fee_summary else "",
                        f"Hours: {hours_summary}" if hours_summary else "",
                        f"Weather: {park_record.get('weather_info')}" if park_record.get("weather_info") else "",
                    ]
                )
            )

            store.upsert_park(park_record)
            store.add_source_chunk(
                {
                    "park_code": park_code,
                    "source_type": "nps_api",
                    "source_url": NPS_API_URL,
                    "section": "park_record",
                    "content": readable_context[:2500],
                    "fetched_at": datetime.utcnow().isoformat(),
                }
            )
            upserts += 1

        return {"ingested": upserts, "source": NPS_API_URL}
