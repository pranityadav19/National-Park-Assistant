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
