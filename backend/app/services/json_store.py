from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from app.core.config import settings


class JSONStore:
    def __init__(self, path: str | None = None):
        self.path = Path(path or settings.data_file)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def load(self) -> dict:
        if not self.path.exists():
            return {"parks": [], "source_chunks": [], "updated_at": None}
        with self.path.open("r", encoding="utf-8") as f:
            return json.load(f)

    def save(self, data: dict) -> None:
        data["updated_at"] = datetime.utcnow().isoformat()
        with self.path.open("w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

    def upsert_park(self, park: dict) -> None:
        data = self.load()
        parks = data.get("parks", [])
        code = (park.get("park_code") or "").lower()
        idx = next((i for i, p in enumerate(parks) if (p.get("park_code") or "").lower() == code), None)
        if idx is None:
            parks.append(park)
        else:
            merged = parks[idx]
            merged.update({k: v for k, v in park.items() if v not in (None, "")})
            parks[idx] = merged
        data["parks"] = parks
        self.save(data)

    def add_source_chunk(self, chunk: dict) -> None:
        data = self.load()
        chunks = data.get("source_chunks", [])
        chunks.append(chunk)
        data["source_chunks"] = chunks
        self.save(data)

    def batch_upsert_parks(self, parks: list[dict]) -> None:
        """Load once, upsert all parks, save once."""
        data = self.load()
        existing = data.get("parks", [])
        code_to_idx = {(p.get("park_code") or "").lower(): i for i, p in enumerate(existing)}
        for park in parks:
            code = (park.get("park_code") or "").lower()
            if not code:
                continue
            if code in code_to_idx:
                idx = code_to_idx[code]
                existing[idx].update({k: v for k, v in park.items() if v not in (None, "")})
            else:
                existing.append(park)
                code_to_idx[code] = len(existing) - 1
        data["parks"] = existing
        self.save(data)

    def batch_add_source_chunks(self, chunks: list[dict]) -> None:
        """Load once, add all chunks, save once."""
        if not chunks:
            return
        data = self.load()
        existing = data.get("source_chunks", [])
        existing.extend(chunks)
        data["source_chunks"] = existing
        self.save(data)

    def clear_source_chunks_by_type(self, source_type: str) -> None:
        """Remove all chunks of a given source_type before re-ingesting."""
        data = self.load()
        data["source_chunks"] = [
            c for c in data.get("source_chunks", []) if c.get("source_type") != source_type
        ]
        self.save(data)
