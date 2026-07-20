import json
from dataclasses import dataclass

from agent.events import utc_now
from agent.memory.semantic import clean_memory_text
from agent.memory.store import MemoryStore
from agent.models.base import ModelUnavailable
from agent.models.router import ModelRouter


@dataclass
class ResearchMemoryCandidate:
    should_remember: bool
    kind: str = "web_fact"
    content: str = ""
    importance: int = 4
    confidence: float = 0.0
    reason: str = ""


class ResearchMemoryIngestor:
    def __init__(self, store=None, router=None):
        self.store = store or MemoryStore()
        self.router = router or ModelRouter()

    def ingest(self, result, requested_by="user"):
        if not result or not getattr(result, "sources", None):
            return []

        candidates = self._candidates_from_model(result)

        if not candidates:
            candidates = [self._fallback_candidate(result)]

        stored_ids = []

        for candidate in candidates:
            memory_id = self._store_candidate(
                candidate,
                result,
                requested_by=requested_by
            )

            if memory_id:
                stored_ids.append(memory_id)

        return stored_ids

    def setup_status(self):
        return "Sourced research memory ingestion online."

    def _candidates_from_model(self, result):
        try:
            payload = self.router.generate_json(
                self._prompt(result),
                user_input=result.query,
                routing="research"
            )
        except (ModelUnavailable, ValueError, TypeError, Exception):
            return []

        items = payload.get("memories", [])

        if not isinstance(items, list):
            return []

        candidates = []

        for item in items[:5]:
            if not isinstance(item, dict):
                continue

            candidate = ResearchMemoryCandidate(
                should_remember=bool(item.get("should_remember", False)),
                kind=str(item.get("kind", "web_fact")),
                content=clean_memory_text(item.get("content", "")),
                importance=self._importance(item.get("importance", 4)),
                confidence=self._confidence(item.get("confidence", 0.0)),
                reason=str(item.get("reason", ""))
            )

            if not candidate.content or candidate.confidence < 0.65:
                candidate.should_remember = False

            candidates.append(candidate)

        return candidates

    def _prompt(self, result):
        sources = [
            {
                "title": source.title,
                "url": source.url,
                "snippet": source.snippet
            }
            for source in result.sources
        ]

        payload = {
            "query": result.query,
            "summary": result.summary,
            "confidence": result.confidence,
            "sources": sources
        }

        return (
            "You are Entity's sourced memory ingestor. Decide which durable, "
            "useful facts from this research result should be stored for "
            "future planning. Store only facts supported by the source "
            "snippets. Do not store trivia, secrets, speculation, or facts "
            "that need live freshness unless the memory says it should be "
            "rechecked. Return JSON only.\n\n"
            "Return exactly this JSON shape:\n"
            "{\n"
            '  "memories": [\n'
            "    {\n"
            '      "should_remember": true,\n'
            '      "kind": "web_fact|tool_knowledge|place|routine|preference",\n'
            '      "content": "one sourced memory sentence",\n'
            '      "importance": 5,\n'
            '      "confidence": 0.75,\n'
            '      "reason": "short reason"\n'
            "    }\n"
            "  ]\n"
            "}\n\n"
            f"Research result: {json.dumps(payload)}"
        )

    def _fallback_candidate(self, result):
        content = clean_memory_text(result.summary)

        return ResearchMemoryCandidate(
            should_remember=bool(content),
            kind="web_fact",
            content=content,
            importance=4,
            confidence=max(0.5, min(0.7, result.confidence or 0.5)),
            reason="Fallback memory from sourced research summary."
        )

    def _store_candidate(self, candidate, result, requested_by="user"):
        if not candidate.should_remember:
            return None

        if self._has_exact_memory(candidate.content):
            return None

        return self.store.add_memory(
            kind=candidate.kind,
            content=candidate.content,
            source="research",
            importance=candidate.importance,
            metadata={
                "query": result.query,
                "summary": result.summary,
                "sources": [
                    {
                        "title": source.title,
                        "url": source.url
                    }
                    for source in result.sources
                ],
                "confidence": candidate.confidence,
                "research_confidence": result.confidence,
                "reason": candidate.reason,
                "requested_by": requested_by,
                "retrieved_at": utc_now()
            }
        )

    def _has_exact_memory(self, content):
        normalized = content.lower().strip()

        for memory in self.store.search(content, limit=5):
            if memory["content"].lower().strip() == normalized:
                return True

        return False

    def _importance(self, value):
        try:
            value = int(value)
        except (TypeError, ValueError):
            value = 4

        return min(10, max(1, value))

    def _confidence(self, value):
        try:
            value = float(value)
        except (TypeError, ValueError):
            value = 0.0

        return min(1.0, max(0.0, value))
