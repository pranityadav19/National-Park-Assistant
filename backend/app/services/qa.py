from __future__ import annotations

import difflib
import re
from typing import Any

from app.schemas.park import AskResponse, Citation
from app.services.json_store import JSONStore
from app.utils.text import best_snippets


class QAService:
    SOURCE_PRIORITY = {"nps_api": 0, "nps_site": 1, "wikivoyage": 2, "nps_docs": 3}

    @staticmethod
    def _normalize_name(name: str) -> str:
        cleaned = re.sub(r"[^a-zA-Z0-9\s]", " ", name.lower())
        cleaned = re.sub(
            r"\b(national|park|parks|national\s+park|historical|monument|preserve|memorial|seashore|lakeshore)\b",
            " ",
            cleaned,
        )
        return re.sub(r"\s+", " ", cleaned).strip()

    def _resolve_park(self, parks: list[dict], park_name: str | None, question: str | None) -> dict | None:
        if not parks:
            return None

        if park_name:
            target = park_name.strip().lower()
            exact = next((p for p in parks if (p.get("full_name") or "").lower() == target), None)
            if exact:
                return exact

            contains = next((p for p in parks if target in (p.get("full_name") or "").lower()), None)
            if contains:
                return contains

        if park_name:
            normalized_target = self._normalize_name(park_name)
            if normalized_target:
                norm_contains = next(
                    (
                        p
                        for p in parks
                        if normalized_target in self._normalize_name(p.get("full_name") or "")
                        or self._normalize_name(p.get("full_name") or "") in normalized_target
                    ),
                    None,
                )
                if norm_contains:
                    return norm_contains

                names = [p.get("full_name") or "" for p in parks]
                close = difflib.get_close_matches(park_name, names, n=1, cutoff=0.62)
                if close:
                    return next((p for p in parks if (p.get("full_name") or "") == close[0]), None)

        if question:
            q = question.lower()
            by_question = next((p for p in parks if (p.get("full_name") or "").lower() in q), None)
            if by_question:
                return by_question

            q_norm = self._normalize_name(question)
            by_question_norm = next(
                (
                    p
                    for p in parks
                    if self._normalize_name(p.get("full_name") or "")
                    and self._normalize_name(p.get("full_name") or "") in q_norm
                ),
                None,
            )
            if by_question_norm:
                return by_question_norm

        return None

    @staticmethod
    def _detect_intent(question: str) -> str:
        q = question.lower()

        if any(k in q for k in ["cost", "fee", "price", "ticket", "entrance", "pass"]):
            return "fees"

        if any(k in q for k in ["open", "close", "year round", "hours", "time", "seasonal closure"]):
            return "hours"

        if any(
            k in q
            for k in [
                "best season",
                "best time",
                "when should",
                "weather",
                "winter",
                "summer",
                "spring",
                "fall",
                "autumn",
            ]
        ):
            return "season"

        if any(k in q for k in ["do", "activity", "hike", "camp", "things to do"]):
            return "activities"

        if any(
            k in q
            for k in ["stay", "hotel", "lodging", "accommodation", "where to stay", "nearby town", "towns nearby"]
        ):
            return "lodging"

        if any(k in q for k in ["animal", "animals", "wildlife", "bear", "bison", "elk", "birds", "mammals"]):
            return "wildlife"

        return "general"

    @staticmethod
    def _tokenize(text: str) -> set[str]:
        return {t for t in re.findall(r"[a-zA-Z]{3,}", text.lower())}

    def _retrieve_chunks(self, question: str, chunks: list[dict[str, Any]], limit: int = 4) -> list[dict[str, Any]]:
        q_terms = self._tokenize(question)
        scored: list[tuple[int, dict[str, Any]]] = []

        for chunk in chunks:
            content = (chunk.get("content") or "").strip()
            if not content:
                continue
            if content.startswith("{") and "'id':" in content:
                continue

            c_terms = self._tokenize(content)
            overlap = len(q_terms.intersection(c_terms))
            source_bonus = max(0, 4 - self.SOURCE_PRIORITY.get(chunk.get("source_type", ""), 10))
            score = overlap * 2 + source_bonus
            scored.append((score, chunk))

        scored.sort(key=lambda item: item[0], reverse=True)
        top = [chunk for score, chunk in scored if score > 0][:limit]
        if top:
            return top

        fallback = sorted(chunks, key=lambda c: self.SOURCE_PRIORITY.get(c.get("source_type", ""), 99))
        return [c for c in fallback if (c.get("content") or "").strip()][:limit]

    @staticmethod
    def _extract_evidence(question: str, chunks: list[dict[str, Any]], limit: int = 2) -> str:
        texts = [(c.get("content") or "").strip() for c in chunks if (c.get("content") or "").strip()]
        if not texts:
            return ""

        snippets = best_snippets(question, texts, limit=limit)
        cleaned = []
        for s in snippets:
            one_line = re.sub(r"\s+", " ", s).strip()
            cleaned.append(one_line[:220])

        return " ".join(cleaned)

    def ask(self, question: str, park_code: str | None = None, park_name: str | None = None) -> AskResponse:
        store = JSONStore()
        data = store.load()
        parks = data.get("parks", [])
        chunks = data.get("source_chunks", [])

        park = None
        if park_code:
            park = next((p for p in parks if (p.get("park_code") or "").lower() == park_code.lower()), None)

        if not park:
            park = self._resolve_park(parks, park_name=park_name, question=question)

        if not park:
            return AskResponse(
                answer="I could not confidently match the requested park. Please try a more specific park name.",
                confidence_note="Low confidence: park name could not be resolved confidently.",
                citations=[],
            )

        park_code_value = park.get("park_code")
        scoped = [c for c in chunks if c.get("park_code") in (park_code_value, None)]
        scoped.sort(key=lambda c: self.SOURCE_PRIORITY.get(c.get("source_type", ""), 99))

        retrieved = self._retrieve_chunks(question, scoped, limit=4)
        context_text = self._extract_evidence(question, retrieved, limit=2)
        intent = self._detect_intent(question)

        fee = park.get("entrance_fee_summary") or "No official fee data available in current records."
        hours = park.get("operating_hours_summary") or "Operating hours not currently available."
        weather = park.get("weather_info") or "Season guidance is limited in current records."
        description = park.get("description") or "No additional summary available."

        park_title = park.get("full_name", "Park")

        if intent == "fees":
            answer = f"{park_title}: Current entrance fees: {fee}"
            if "no official fee data" in fee.lower():
                answer += f" {description}"

        elif intent == "hours":
            answer = f"{park_title}: Open/access guidance: {hours}"

        elif intent == "season":
            answer = (
                f"{park_title}: The best time to visit is usually spring or fall, "
                f"when weather conditions are often more comfortable. {weather}"
            )

        elif intent == "activities":
            answer = f"{park_title}: {description} Hours/access: {hours}"

        elif intent == "lodging":
            answer = f"{park_title}: Nearby stay and travel guidance: {context_text or description}"

        elif intent == "wildlife":
            answer = f"{park_title}: Wildlife guidance: {context_text or description}"

        else:
            answer = f"{park_title}: {context_text or description}"

        citations = [
            Citation(
                source_type=c.get("source_type", "unknown"),
                source_url=c.get("source_url", ""),
                section=c.get("section"),
            )
            for c in retrieved[:5]
            if c.get("source_url")
        ]

        return AskResponse(
            answer=answer,
            confidence_note=(
                f"Intent detected: {intent}. "
                "Answer grounded in retrieved NPS/Wikivoyage cache snippets; "
                "verify official alerts for real-time closures."
            ),
            citations=citations,
        )