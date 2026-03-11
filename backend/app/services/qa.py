from __future__ import annotations

import difflib
import re
from typing import Any

from app.schemas.park import AskResponse, Citation
from app.services.json_store import JSONStore
from app.utils.text import best_snippets


class QAService:
    SOURCE_PRIORITY = {"nps_api": 0, "nps_site": 1, "wikivoyage": 2, "nps_docs": 3}

    # Maps intent → preferred section name(s) in source chunks
    INTENT_SECTIONS: dict[str, list[str]] = {
        "fees": ["park_overview"],
        "hours": ["park_overview", "visitor_centers"],
        "season": ["park_overview", "travel_guide"],
        "camping": ["campgrounds"],
        "activities": ["things_to_do", "main", "plan_your_visit"],
        "trails": ["things_to_do", "main", "plan_your_visit", "nature"],
        "directions": ["plan_your_visit", "main", "travel_guide"],
        "visitor_center": ["visitor_centers"],
        "lodging": ["travel_guide", "plan_your_visit"],
        "wildlife": ["nature", "travel_guide", "park_overview"],
        "history": ["history_culture", "travel_guide", "park_overview"],
        "geology": ["nature", "travel_guide", "park_overview"],
        "accessibility": ["plan_your_visit", "main"],
        "pets": ["plan_your_visit", "main", "travel_guide", "things_to_do", "park_overview"],
        "permits": ["plan_your_visit", "things_to_do"],
        "dining": ["plan_your_visit", "travel_guide"],
        "transportation": ["plan_your_visit", "travel_guide"],
        "photography": ["plan_your_visit", "main"],
        "alerts": ["alerts"],
        "general": [],
    }

    # Extra terms added to the question when scoring paragraphs for each intent,
    # so that content-rich paragraphs beat incidentally-matching ones.
    INTENT_AUGMENT: dict[str, str] = {
        "wildlife": "animal species fauna bird mammal reptile fish amphibian insect habitat ecosystem",
        "history": "history historical culture heritage indigenous ancient tribe artifact settlement",
        "geology": "geology rock formation volcano glacier cave canyon fossil mineral landscape",
        "camping": "campground tent site reservation backcountry primitive amenity",
        "trails": "trail hike hiking walk route distance elevation summit backpack mileage",
        "directions": "driving distance entrance gate road highway miles airport city",
        "dining": "food restaurant cafe eat dining drink water refill concession",
        "lodging": "hotel lodge stay accommodation cabin motel inn room",
        "transportation": "shuttle bus parking transit ride",
        "accessibility": "accessible wheelchair disability ada mobility ramp",
        "permits": "permit reservation lottery timed entry quota book advance",
        "photography": "photography filming drone camera permit tripod video",
        "activities": "activity hike swim kayak fish climb boat ranger program tour",
        "alerts": "alert closure warning fire flood emergency hazard closed",
        "visitor_center": "visitor center hours open contact information exhibits",
        "season": "season weather temperature rain snow climate dry wet crowd",
        "fees": "fee cost price entrance adult vehicle motorcycle annual pass",
        "hours": "open close hours daily season year round access gate",
        "pets": "pet pets dog dogs leash allowed prohibited rules bring animal paved road backcountry",
    }

    @staticmethod
    def _normalize_name(name: str) -> str:
        cleaned = re.sub(r"[^a-zA-Z0-9\s]", " ", name.lower())
        cleaned = re.sub(
            r"\b(national|park|parks|historical|monument|preserve|memorial|seashore|lakeshore|recreation|area|scenic|riverway|parkway|battlefield|historic|site)\b",
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
            # Try longest park name match first to avoid partial matches (e.g. "Wind Cave" before "Cave")
            sorted_parks = sorted(parks, key=lambda p: len(p.get("full_name") or ""), reverse=True)
            by_question = next(
                (p for p in sorted_parks if (p.get("full_name") or "").lower() in q), None
            )
            if by_question:
                return by_question

            q_norm = self._normalize_name(question)
            by_question_norm = next(
                (
                    p
                    for p in sorted_parks
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

        # Alerts/closures — check early as they're time-sensitive
        if any(k in q for k in ["alert", "closure", "closed", "warning", "fire", "flood", "emergency", "shutdown"]):
            return "alerts"

        # Fees and costs
        if any(k in q for k in ["cost", "fee", "fees", "price", "ticket", "entrance", "pass", "charge", "pay", "free", "annual pass", "america the beautiful", "how much"]):
            return "fees"

        # Hours and access
        if any(k in q for k in ["open", "close", "hours", "year round", "seasonal closure", "when does", "access"]):
            return "hours"

        # Camping
        if any(k in q for k in ["camp", "camping", "campground", "campsite", "tent", " rv ", "camper", "backcountry camp", "overnight", "sleep in park"]):
            return "camping"

        # Trails and hiking
        if any(k in q for k in ["trail", "trails", "hike", "hiking", "hikes", "walk", "backpack", "backpacking", "trek", "trekking", "route", "path", "distance", "miles", "elevation", "summit", "climb the mountain"]):
            return "trails"

        # Directions / getting there
        if any(k in q for k in ["direction", "directions", "how to get", "how do i get", "how to reach", "getting there", "get there", "get to the park", "drive", "driving", "fly", "airport", "nearest city", "closest city", "entrance station", "entrance gate", "from las vegas", "from denver", "from phoenix", "nearest town", "road trip"]):
            return "directions"

        # Visitor centers
        if any(k in q for k in ["visitor center", "visitors center", "information center", "ranger station", "park headquarters"]):
            return "visitor_center"

        # Lodging / accommodation
        if any(k in q for k in ["stay", "hotel", "lodging", "accommodation", "lodge", "cabin", "inn", "motel", "airbnb", "where to stay", "nearby town", "sleep", "overnight options"]):
            return "lodging"

        # Wildlife / fauna
        if any(k in q for k in ["animal", "animals", "wildlife", "bear", "bears", "bison", "elk", "wolf", "wolves", "bird", "birds", "mammal", "fish", "reptile", "fauna", "deer", "moose", "alligator", "condor", "pronghorn"]):
            return "wildlife"

        # Weather / seasons / best time
        if any(k in q for k in ["weather", "best season", "best time", "when should", "when to visit", "climate", "temperature", "rain", "snow", "winter", "summer", "spring", "fall", "autumn", "crowd", "crowded", "busy season", "off season", "off-season"]):
            return "season"

        # History and culture
        if any(k in q for k in ["history", "historical", "culture", "cultural", "native", "indigenous", "heritage", "artifact", "historic", "civilization", "people", "tribe", "ancient", "petroglyph", "pictograph", "civil war", "settlement"]):
            return "history"

        # Geology / natural features / flora
        if any(k in q for k in ["geology", "geological", "rock", "formation", "volcano", "volcanic", "geyser", "cave", "canyon", "glacier", "glacial", "fossil", "mineral", "nature", "ecosystem", "plant", "flora", "tree", "forest", "desert", "dune", "hot spring", "arch", "mesa", "butte"]):
            return "geology"

        # Accessibility
        if any(k in q for k in ["accessible", "accessibility", "wheelchair", "disability", "disabled", "ada", "mobility", "impaired", "special needs"]):
            return "accessibility"

        # Pets / dogs
        if any(k in q for k in ["pet", "pets", "dog", "dogs", "leash", "bring my dog", "animals allowed", "bring my cat"]):
            return "pets"

        # Permits / reservations / timed entry
        if any(k in q for k in ["permit", "permits", "reservation", "lottery", "timed entry", "quota", "recreation.gov", "advance booking", "book in advance"]):
            return "permits"

        # Dining / food
        if any(k in q for k in ["food", "restaurant", "dining", "eat", "snack", "grocery", "cafe", "cafeteria", "picnic", "drink", "water bottle", "refill", "concession"]):
            return "dining"

        # Transportation / getting around
        if any(k in q for k in ["shuttle", "bus", "parking", "public transit", "transport", "transportation", "ride", "taxi", "uber", "traffic", "congestion"]):
            return "transportation"

        # Photography
        if any(k in q for k in ["photo", "photography", "filming", "drone", "camera", "tripod", "video", "instagram"]):
            return "photography"

        # Activities (broad — last before general)
        if any(k in q for k in ["activity", "activities", "things to do", "swim", "kayak", "canoe", "fish", "fishing", "ranger program", "guided tour", "junior ranger", "visitor program", "tour", "boat"]):
            return "activities"

        return "general"

    @staticmethod
    def _tokenize(text: str) -> set[str]:
        return {t for t in re.findall(r"[a-zA-Z]{3,}", text.lower())}

    def _retrieve_chunks(
        self, question: str, chunks: list[dict[str, Any]], intent: str = "general", limit: int = 6
    ) -> list[dict[str, Any]]:
        q_terms = self._tokenize(question)
        preferred_sections = set(self.INTENT_SECTIONS.get(intent, []))
        scored: list[tuple[float, dict[str, Any]]] = []

        for chunk in chunks:
            content = (chunk.get("content") or "").strip()
            if not content:
                continue

            c_terms = self._tokenize(content)
            overlap = len(q_terms.intersection(c_terms))
            source_bonus = max(0, 4 - self.SOURCE_PRIORITY.get(chunk.get("source_type", ""), 10))
            section_bonus = 5 if chunk.get("section") in preferred_sections else 0
            score = overlap * 2 + source_bonus + section_bonus
            scored.append((score, chunk))

        scored.sort(key=lambda item: item[0], reverse=True)
        top = [chunk for score, chunk in scored if score > 0][:limit]
        if top:
            return top

        fallback = sorted(chunks, key=lambda c: self.SOURCE_PRIORITY.get(c.get("source_type", ""), 99))
        return [c for c in fallback if (c.get("content") or "").strip()][:limit]

    @staticmethod
    def _extract_evidence(
        question: str,
        chunks: list[dict[str, Any]],
        limit: int = 4,
        required_terms: set[str] | None = None,
    ) -> str:
        """
        Extract the most relevant paragraphs from chunks.
        If required_terms is provided, a paragraph must contain at least one of
        those terms — this prevents park-name words alone from causing false matches.
        """
        q_terms = {t.lower() for t in re.findall(r"[a-zA-Z]{3,}", question)}
        if not q_terms:
            return ""

        scored_paragraphs: list[tuple[int, str]] = []

        for chunk in chunks:
            content = (chunk.get("content") or "").strip()
            if not content:
                continue

            paragraphs = [p.strip() for p in re.split(r"\n|\s*\|\s*", content) if p.strip()]

            for para in paragraphs:
                if len(para) < 40:
                    continue
                lower = para.lower()
                # Must contain at least one intent-specific term when required
                if required_terms and not any(t in lower for t in required_terms):
                    continue
                score = sum(1 for t in q_terms if t in lower)
                if score >= 1:
                    scored_paragraphs.append((score, para))

        if not scored_paragraphs:
            return ""

        scored_paragraphs.sort(key=lambda x: x[0], reverse=True)
        seen: set[str] = set()
        results: list[str] = []
        for _, para in scored_paragraphs:
            key = para[:60]
            if key not in seen:
                seen.add(key)
                results.append(re.sub(r"\s+", " ", para).strip()[:500])
            if len(results) >= limit:
                break

        return " | ".join(results)

    def _chunks_for_sections(self, scoped: list[dict], sections: list[str]) -> list[dict]:
        """Return chunks whose section is in the given list."""
        return [c for c in scoped if c.get("section") in sections]

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
                confidence_note="Low confidence: park name could not be resolved.",
                citations=[],
            )

        park_code_value = park.get("park_code")
        scoped = [c for c in chunks if c.get("park_code") in (park_code_value, None)]

        intent = self._detect_intent(question)
        augment_str = self.INTENT_AUGMENT.get(intent, "")
        augmented_q = question + " " + augment_str
        # Required terms prevent park-name words from being the sole match
        required_terms: set[str] | None = (
            {t.lower() for t in re.findall(r"[a-zA-Z]{3,}", augment_str)} if augment_str else None
        )
        retrieved = self._retrieve_chunks(question, scoped, intent=intent, limit=6)
        context_text = self._extract_evidence(augmented_q, retrieved, limit=2, required_terms=required_terms)

        fee = park.get("entrance_fee_summary") or ""
        hours = park.get("operating_hours_summary") or ""
        weather = park.get("weather_info") or ""
        description = park.get("description") or ""
        park_title = park.get("full_name", "Park")
        park_url = park.get("url", "")
        url_note = f" More info: {park_url}" if park_url else ""

        if intent == "fees":
            if fee:
                # Split fee summary into individual entries and return only the most relevant ones
                entries = [e.strip() for e in re.split(r";(?=\s*[A-Z])", fee) if e.strip()]
                if len(entries) > 1:
                    # Strip generic and park-name words so they don't skew scoring
                    park_tokens = {t.lower() for t in re.findall(r"[a-zA-Z]{3,}", park_title)}
                    stop = {"how", "much", "does", "cost", "much", "what", "the", "fee", "fees",
                            "entrance", "price", "ticket", "pay", "tell", "about", "for", "get", "into"}
                    q_fee_terms = [t.lower() for t in re.findall(r"[a-zA-Z]{3,}", question)
                                   if t.lower() not in stop and t.lower() not in park_tokens]
                    q_bigrams = {f"{q_fee_terms[i]} {q_fee_terms[i+1]}" for i in range(len(q_fee_terms) - 1)}
                    scored_entries = []
                    for entry in entries:
                        entry_lower = entry.lower()
                        # Use whole-word matching to avoid "enter" matching "entering"
                        score = sum(2 for bg in q_bigrams if re.search(r'\b' + re.escape(bg) + r'\b', entry_lower))
                        score += sum(1 for t in q_fee_terms if re.search(r'\b' + re.escape(t) + r'\b', entry_lower))
                        scored_entries.append((score, entry))
                    scored_entries.sort(key=lambda x: x[0], reverse=True)
                    top_score = scored_entries[0][0]
                    if top_score >= 1 and q_fee_terms:
                        # Specific match found — return just the best entry
                        relevant = [scored_entries[0][1]]
                    else:
                        # General question — default to private vehicle + per person
                        relevant = [e for e in entries if "private vehicle" in e.lower()][:1]
                        relevant += [e for e in entries if "per person" in e.lower()][:1]
                        relevant = relevant or entries[:2]
                    answer = f"{park_title} entrance fees: {'; '.join(relevant)}{url_note}"
                else:
                    answer = f"{park_title} entrance fees: {fee}{url_note}"
            else:
                answer = f"{park_title}: {context_text or description}{url_note}"

        elif intent == "hours":
            if hours:
                answer = f"{park_title} hours & access: {hours}{url_note}"
            else:
                answer = f"{park_title}: {context_text or description}{url_note}"

        elif intent == "season":
            if weather:
                answer = f"{park_title} — when to visit: {weather}"
            elif context_text:
                answer = f"{park_title} — best time to visit: {context_text}"
            else:
                answer = f"{park_title}: Season information is not available in current records.{url_note}"

        elif intent == "camping":
            camping_chunks = self._chunks_for_sections(scoped, ["campgrounds"])
            camp_ctx = self._extract_evidence(augmented_q, camping_chunks, limit=2, required_terms=required_terms) if camping_chunks else context_text
            answer = f"{park_title} camping: {camp_ctx or 'No campground data available. Check recreation.gov for reservations.'}{url_note}"

        elif intent == "trails":
            trail_chunks = self._chunks_for_sections(scoped, ["things_to_do", "main", "plan_your_visit", "nature"])
            trail_ctx = self._extract_evidence(augmented_q, trail_chunks, limit=2, required_terms=required_terms) if trail_chunks else context_text
            answer = f"{park_title} trails & hiking: {trail_ctx or description}{url_note}"

        elif intent == "directions":
            dir_chunks = self._chunks_for_sections(scoped, ["plan_your_visit", "main", "travel_guide"])
            dir_ctx = self._extract_evidence(augmented_q, dir_chunks, limit=2, required_terms=required_terms) if dir_chunks else context_text
            answer = f"{park_title} — getting there: {dir_ctx or description}{url_note}"

        elif intent == "visitor_center":
            vc_chunks = self._chunks_for_sections(scoped, ["visitor_centers"])
            vc_ctx = self._extract_evidence(augmented_q, vc_chunks, limit=2, required_terms=required_terms) if vc_chunks else context_text
            answer = f"{park_title} visitor centers: {vc_ctx or 'Visitor center details not available. Check nps.gov.'}{url_note}"

        elif intent == "lodging":
            lodging_chunks = self._chunks_for_sections(scoped, ["travel_guide", "plan_your_visit"])
            lodging_ctx = self._extract_evidence(augmented_q, lodging_chunks, limit=2, required_terms=required_terms) if lodging_chunks else context_text
            answer = f"{park_title} lodging & accommodation: {lodging_ctx or description}{url_note}"

        elif intent == "wildlife":
            wildlife_chunks = self._chunks_for_sections(scoped, ["nature", "travel_guide", "park_overview"])
            wl_ctx = self._extract_evidence(augmented_q, wildlife_chunks, limit=2, required_terms=required_terms) if wildlife_chunks else context_text
            answer = f"{park_title} wildlife: {wl_ctx or description}{url_note}"

        elif intent == "history":
            hist_chunks = self._chunks_for_sections(scoped, ["history_culture", "travel_guide", "park_overview"])
            hist_ctx = self._extract_evidence(augmented_q, hist_chunks, limit=2, required_terms=required_terms) if hist_chunks else context_text
            answer = f"{park_title} history & culture: {hist_ctx or description}{url_note}"

        elif intent == "geology":
            geo_chunks = self._chunks_for_sections(scoped, ["nature", "travel_guide", "park_overview"])
            geo_ctx = self._extract_evidence(augmented_q, geo_chunks, limit=2, required_terms=required_terms) if geo_chunks else context_text
            answer = f"{park_title} natural features & geology: {geo_ctx or description}{url_note}"

        elif intent == "accessibility":
            acc_chunks = self._chunks_for_sections(scoped, ["plan_your_visit", "main"])
            acc_ctx = self._extract_evidence(augmented_q, acc_chunks, limit=2, required_terms=required_terms) if acc_chunks else context_text
            answer = f"{park_title} accessibility: {acc_ctx or 'Check nps.gov for detailed accessibility information.'}{url_note}"

        elif intent == "pets":
            pet_chunks = self._chunks_for_sections(scoped, ["plan_your_visit", "main", "travel_guide", "things_to_do", "park_overview"])
            pet_ctx = self._extract_evidence(augmented_q, pet_chunks, limit=2, required_terms=required_terms) if pet_chunks else context_text
            answer = f"{park_title} pet policy: {pet_ctx or 'Check nps.gov for current pet/dog regulations.'}{url_note}"

        elif intent == "permits":
            permit_chunks = self._chunks_for_sections(scoped, ["plan_your_visit", "things_to_do"])
            permit_ctx = self._extract_evidence(augmented_q, permit_chunks, limit=2, required_terms=required_terms) if permit_chunks else context_text
            answer = f"{park_title} permits & reservations: {permit_ctx or 'Check recreation.gov for permit lotteries and reservations.'}{url_note}"

        elif intent == "dining":
            dining_chunks = self._chunks_for_sections(scoped, ["plan_your_visit", "travel_guide"])
            dining_ctx = self._extract_evidence(augmented_q, dining_chunks, limit=2, required_terms=required_terms) if dining_chunks else context_text
            answer = f"{park_title} food & dining: {dining_ctx or description}{url_note}"

        elif intent == "transportation":
            trans_chunks = self._chunks_for_sections(scoped, ["plan_your_visit", "travel_guide"])
            trans_ctx = self._extract_evidence(augmented_q, trans_chunks, limit=2, required_terms=required_terms) if trans_chunks else context_text
            answer = f"{park_title} transportation & parking: {trans_ctx or description}{url_note}"

        elif intent == "photography":
            photo_chunks = self._chunks_for_sections(scoped, ["plan_your_visit", "main"])
            photo_ctx = self._extract_evidence(augmented_q, photo_chunks, limit=2, required_terms=required_terms) if photo_chunks else context_text
            answer = f"{park_title} photography: {photo_ctx or 'Check nps.gov for photography and filming regulations.'}{url_note}"

        elif intent == "activities":
            act_chunks = self._chunks_for_sections(scoped, ["things_to_do", "main", "plan_your_visit"])
            act_ctx = self._extract_evidence(augmented_q, act_chunks, limit=2, required_terms=required_terms) if act_chunks else context_text
            answer = f"{park_title} activities: {act_ctx or description}{url_note}"

        elif intent == "alerts":
            alert_chunks = self._chunks_for_sections(scoped, ["alerts"])
            alert_ctx = self._extract_evidence(augmented_q, alert_chunks, limit=2, required_terms=required_terms) if alert_chunks else context_text
            if alert_ctx:
                answer = f"{park_title} current alerts & closures: {alert_ctx}{url_note}"
            else:
                answer = f"{park_title}: No active alerts in current records. Check nps.gov/alerts for real-time information.{url_note}"

        else:
            answer = f"{park_title}: {context_text or description}{url_note}"

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
                "Answer grounded in NPS API, NPS.gov, and Wikivoyage data. "
                "Verify nps.gov for real-time alerts and closures."
            ),
            citations=citations,
        )
