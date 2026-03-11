from __future__ import annotations

import asyncio
from collections import defaultdict
from datetime import datetime

import httpx

from app.core.config import settings
from app.services.json_store import JSONStore
from app.utils.text import normalize_whitespace

NPS_BASE = "https://developer.nps.gov/api/v1"


class NPSAPIIngestor:
    async def _get_all(
        self, client: httpx.AsyncClient, endpoint: str, extra_params: dict | None = None, max_items: int = 10000
    ) -> list:
        """Fetch results from a paginated NPS API endpoint up to max_items."""
        headers = {"X-Api-Key": settings.nps_api_key} if settings.nps_api_key else {}
        all_data: list = []
        start = 0
        page_size = 500

        while len(all_data) < max_items:
            params = {"limit": page_size, "start": start, **(extra_params or {})}
            try:
                resp = await client.get(f"{NPS_BASE}/{endpoint}", params=params, headers=headers)
                resp.raise_for_status()
                payload = resp.json()
            except Exception:
                break

            batch = payload.get("data", [])
            if not batch:
                break
            all_data.extend(batch)

            total = int(payload.get("total", 0))
            start += len(batch)
            if start >= total or len(batch) < page_size:
                break

        return all_data

    async def ingest(self, limit: int = 500) -> dict:
        store = JSONStore()
        now = datetime.utcnow().isoformat()

        # Use a generous per-request timeout; each _get_all may make many sequential calls
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            # Fetch core data in parallel (these paginate quickly)
            parks_data, campgrounds_data, vcs_data, alerts_data = await asyncio.gather(
                self._get_all(client, "parks"),
                self._get_all(client, "campgrounds"),
                self._get_all(client, "visitorcenters"),
                self._get_all(client, "alerts"),
                return_exceptions=True,
            )

        # Fetch high-volume endpoints separately to avoid connection contention
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            activities_data = await self._get_all(client, "thingstodo")

        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            articles_data = await self._get_all(client, "articles", max_items=2000)

        # Normalize any failed fetches to empty lists
        def safe(result):
            return result if isinstance(result, list) else []

        parks_data = safe(parks_data)
        campgrounds_data = safe(campgrounds_data)
        activities_data = safe(activities_data)
        vcs_data = safe(vcs_data)
        alerts_data = safe(alerts_data)
        articles_data = safe(articles_data)

        # Group supplemental data by park code.
        # Some endpoints use a top-level "parkCode" field (campgrounds, visitorcenters, alerts).
        # Others use a "relatedParks" array (thingstodo, articles).
        def group_by_park(items: list) -> dict[str, list]:
            out: dict[str, list] = defaultdict(list)
            for item in items:
                # Try top-level parkCode first
                top_code = item.get("parkCode", "")
                if top_code:
                    for pc in top_code.split(","):
                        pc = pc.strip()
                        if pc:
                            out[pc].append(item)
                else:
                    # Fall back to relatedParks array
                    for rp in item.get("relatedParks", []):
                        pc = (rp.get("parkCode") or "").strip()
                        if pc:
                            out[pc].append(item)
            return out

        campgrounds_by_park = group_by_park(campgrounds_data)
        activities_by_park = group_by_park(activities_data)
        vcs_by_park = group_by_park(vcs_data)
        alerts_by_park = group_by_park(alerts_data)
        articles_by_park = group_by_park(articles_data)

        park_records: list[dict] = []
        new_chunks: list[dict] = []

        for item in parks_data:
            park_code = item.get("parkCode")
            if not park_code:
                continue

            # --- Fees (all fees + passes) ---
            fees = item.get("entranceFees", [])
            passes = item.get("entrancePasses", [])
            fee_parts = [
                normalize_whitespace(f"{f.get('title', 'Fee')}: ${f.get('cost', 'N/A')} — {f.get('description', '')}")
                for f in fees
            ]
            for p in passes:
                fee_parts.append(
                    normalize_whitespace(
                        f"Pass — {p.get('title', '')}: ${p.get('cost', 'N/A')} — {p.get('description', '')}"
                    )
                )
            fee_summary = "; ".join(fee_parts) if fee_parts else None

            # --- Operating Hours (all entries) ---
            hours_entries = item.get("operatingHours", [])
            hours_parts = []
            for h in hours_entries:
                name = h.get("name", "Hours")
                desc = h.get("description", "")
                exceptions = h.get("exceptions", [])
                exc_text = (
                    "; ".join(f"{e.get('name', '')}: {e.get('exceptionHours', '')}" for e in exceptions[:3])
                    if exceptions
                    else ""
                )
                hours_parts.append(normalize_whitespace(f"{name}: {desc} {exc_text}"))
            hours_summary = " | ".join(hours_parts) if hours_parts else None

            # --- Activities & Topics ---
            activities_list = [a.get("name", "") for a in item.get("activities", []) if a.get("name")]
            topics_list = [t.get("name", "") for t in item.get("topics", []) if t.get("name")]

            # --- Address & Contacts ---
            addresses = item.get("addresses", [])
            address_parts = [
                f"{a.get('type', '')}: {a.get('line1', '')} {a.get('city', '')}, {a.get('stateCode', '')} {a.get('postalCode', '')}".strip()
                for a in addresses
            ]
            contacts = item.get("contacts", {})
            phone_numbers = [p.get("phoneNumber", "") for p in contacts.get("phoneNumbers", []) if p.get("phoneNumber")]
            emails = [e.get("emailAddress", "") for e in contacts.get("emailAddresses", []) if e.get("emailAddress")]

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
                "designation": item.get("designation"),
            }
            park_records.append(park_record)

            # --- Chunk 1: Core park overview ---
            core_parts = [
                f"{park_record['full_name']} ({item.get('designation', 'NPS Unit')}, {park_record.get('states', 'N/A')})",
                park_record.get("description") or "",
                f"Entrance Fees: {fee_summary}" if fee_summary else "",
                f"Operating Hours: {hours_summary}" if hours_summary else "",
                f"Weather & Seasons: {park_record.get('weather_info')}" if park_record.get("weather_info") else "",
                f"Activities offered: {', '.join(activities_list)}" if activities_list else "",
                f"Topics: {', '.join(topics_list)}" if topics_list else "",
                f"Address: {'; '.join(p for p in address_parts if p)}" if address_parts else "",
                f"Phone: {', '.join(phone_numbers)}" if phone_numbers else "",
                f"Email: {', '.join(emails)}" if emails else "",
                f"Website: {park_record.get('url')}" if park_record.get("url") else "",
            ]
            core_content = normalize_whitespace(" | ".join(p for p in core_parts if p))[:4000]
            new_chunks.append({
                "park_code": park_code,
                "source_type": "nps_api",
                "source_url": f"{NPS_BASE}/parks",
                "section": "park_overview",
                "content": core_content,
                "fetched_at": now,
            })

            # --- Chunk 2: Campgrounds ---
            cgs = campgrounds_by_park.get(park_code, [])
            if cgs:
                cg_parts = []
                for cg in cgs[:15]:
                    cg_name = cg.get("name", "Campground")
                    cg_desc = normalize_whitespace(cg.get("description", ""))
                    cg_dir = normalize_whitespace(cg.get("directionsInfo", ""))
                    cg_fees = "; ".join(
                        f"{f.get('title', 'Fee')}: ${f.get('cost', '?')}"
                        for f in cg.get("fees", [])
                    )
                    amenities = cg.get("amenities", {})
                    reservations = normalize_whitespace(cg.get("reservationInfo", ""))
                    cg_text = normalize_whitespace(
                        f"{cg_name}: {cg_desc} | Directions: {cg_dir} | Fees: {cg_fees} | "
                        f"Tent sites: {amenities.get('tentOnly', '?')}, RV sites: {amenities.get('rvOnly', '?')} | "
                        f"Reservations: {reservations}"
                    )
                    cg_parts.append(cg_text)
                new_chunks.append({
                    "park_code": park_code,
                    "source_type": "nps_api",
                    "source_url": f"{NPS_BASE}/campgrounds",
                    "section": "campgrounds",
                    "content": f"Campgrounds at {park_record['full_name']}:\n" + "\n".join(cg_parts)[:4000],
                    "fetched_at": now,
                })

            # --- Chunk 3: Things to do / Activities ---
            acts = activities_by_park.get(park_code, [])
            if acts:
                act_parts = []
                for act in acts[:25]:
                    title = act.get("title", "")
                    short = normalize_whitespace(act.get("shortDescription", ""))
                    activity_names = ", ".join(a.get("name", "") for a in act.get("activities", []) if a.get("name"))
                    duration = act.get("duration", "")
                    act_parts.append(
                        normalize_whitespace(f"{title}: {short} | Activities: {activity_names} | Duration: {duration}")
                    )
                new_chunks.append({
                    "park_code": park_code,
                    "source_type": "nps_api",
                    "source_url": f"{NPS_BASE}/thingstodo",
                    "section": "things_to_do",
                    "content": f"Things to do at {park_record['full_name']}:\n" + "\n".join(act_parts)[:4000],
                    "fetched_at": now,
                })

            # --- Chunk 4: Visitor Centers ---
            vcs = vcs_by_park.get(park_code, [])
            if vcs:
                vc_parts = []
                for vc in vcs[:8]:
                    vc_name = vc.get("name", "Visitor Center")
                    vc_desc = normalize_whitespace(vc.get("description", ""))
                    vc_dir = normalize_whitespace(vc.get("directionsInfo", ""))
                    vc_hours = " | ".join(
                        normalize_whitespace(f"{h.get('name', '')}: {h.get('description', '')}")
                        for h in vc.get("operatingHours", [])
                    )
                    vc_parts.append(
                        normalize_whitespace(f"{vc_name}: {vc_desc} | Directions: {vc_dir} | Hours: {vc_hours}")
                    )
                new_chunks.append({
                    "park_code": park_code,
                    "source_type": "nps_api",
                    "source_url": f"{NPS_BASE}/visitorcenters",
                    "section": "visitor_centers",
                    "content": f"Visitor Centers at {park_record['full_name']}:\n" + "\n".join(vc_parts)[:3000],
                    "fetched_at": now,
                })

            # --- Chunk 5: Current Alerts ---
            alerts = alerts_by_park.get(park_code, [])
            if alerts:
                alert_parts = [
                    normalize_whitespace(
                        f"{a.get('category', 'Alert')} — {a.get('title', '')}: {a.get('description', '')}"
                    )
                    for a in alerts[:10]
                ]
                new_chunks.append({
                    "park_code": park_code,
                    "source_type": "nps_api",
                    "source_url": f"{NPS_BASE}/alerts",
                    "section": "alerts",
                    "content": f"Current alerts at {park_record['full_name']}:\n" + "\n".join(alert_parts)[:2500],
                    "fetched_at": now,
                })

            # --- Chunk 6: Articles / Guides ---
            arts = articles_by_park.get(park_code, [])
            if arts:
                art_parts = [
                    normalize_whitespace(f"{a.get('title', '')}: {a.get('listingDescription', '')}")
                    for a in arts[:10]
                ]
                new_chunks.append({
                    "park_code": park_code,
                    "source_type": "nps_api",
                    "source_url": f"{NPS_BASE}/articles",
                    "section": "articles",
                    "content": f"Articles & guides for {park_record['full_name']}:\n" + "\n".join(art_parts)[:3000],
                    "fetched_at": now,
                })

        # Batch write — clear old nps_api chunks first to avoid duplicates
        store.clear_source_chunks_by_type("nps_api")
        store.batch_upsert_parks(park_records)
        store.batch_add_source_chunks(new_chunks)

        return {"ingested": len(park_records), "chunks": len(new_chunks), "source": NPS_BASE}
