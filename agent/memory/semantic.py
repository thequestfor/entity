import re
from dataclasses import dataclass

from agent.events import Event
from agent.models.base import ModelUnavailable
from agent.models.router import ModelRouter


PREFERENCE_MARKERS = (
    "i prefer",
    "i like",
    "i don't like",
    "i do not like",
    "remember that i",
    "remember i",
    "my preference is"
)

FACT_MARKERS = (
    "my name is",
    "i am",
    "i live",
    "i work",
    "my birthday",
    "remember that"
)

HIGH_IMPORTANCE_EVENT_TYPES = {
    "safety",
    "security",
    "calendar",
    "reminder",
    "unknown_person",
    "user_distress"
}


@dataclass
class MemoryCandidate:
    should_remember: bool
    kind: str = "event"
    content: str = ""
    importance: int = 0
    source: str = "unknown"
    sensitivity: str = "private"
    ttl: int | None = None
    requires_confirmation: bool = False
    reason: str = ""

    def to_memory_kwargs(self):
        return {
            "kind": self.kind,
            "content": self.content,
            "source": self.source,
            "importance": self.importance,
            "metadata": {
                "sensitivity": self.sensitivity,
                "ttl": self.ttl,
                "requires_confirmation": self.requires_confirmation,
                "reason": self.reason
            }
        }


class MemoryEvaluator:
    def __init__(self, router=None):
        self.router = router or ModelRouter()

    def evaluate_text(
        self,
        text,
        source="conversation",
        state=None,
        context=None
    ):
        prompt = self._prompt(
            observation=text,
            source=source,
            state=state,
            context=context
        )

        try:
            payload = self.router.generate_json(prompt)
            return self._candidate_from_model(payload, source)
        except (ModelUnavailable, ValueError, KeyError, TypeError):
            return self._fallback_text(text, source)

    def evaluate_event(self, event, state=None, context=None):
        if isinstance(event, Event):
            observation = event.message or str(event.payload)
            source = event.source
            event_type = event.type
            priority = event.priority
        else:
            observation = str(event)
            source = "event"
            event_type = "event"
            priority = 0

        prompt = self._prompt(
            observation=observation,
            source=source,
            state=state,
            context=context,
            event_type=event_type,
            priority=priority
        )

        try:
            payload = self.router.generate_json(prompt)
            return self._candidate_from_model(payload, source)
        except (ModelUnavailable, ValueError, KeyError, TypeError):
            return self._fallback_event(
                observation,
                source,
                event_type,
                priority
            )

    def _prompt(
        self,
        observation,
        source,
        state=None,
        context=None,
        event_type=None,
        priority=None
    ):
        return f"""
You are Entity's memory evaluator.

Decide whether an observation should become durable memory.
Do not store mundane, repetitive, or invasive details.
Prefer short summaries over raw transcripts.

Return only JSON with these keys:
should_remember: boolean
kind: "fact" | "preference" | "event" | "routine" | "person" | "task"
content: short memory sentence
importance: integer 0-10
sensitivity: "low" | "private" | "sensitive"
ttl: null or seconds until expiry
requires_confirmation: boolean
reason: short reason

Importance:
0-2 ignore
3 working memory only
4-5 low-importance durable memory
6-7 meaningful memory
8-9 notify or ask follow-up
10 urgent safety/security interruption

Source: {source}
Event type: {event_type}
Priority: {priority}
State: {state}
Recent context: {context}
Observation: {observation}
"""

    def _candidate_from_model(self, payload, source):
        candidate = MemoryCandidate(
            should_remember=bool(payload["should_remember"]),
            kind=str(payload.get("kind") or "event"),
            content=clean_memory_text(payload.get("content") or ""),
            importance=self._bounded_importance(
                payload.get("importance", 0)
            ),
            source=source,
            sensitivity=str(payload.get("sensitivity") or "private"),
            ttl=payload.get("ttl"),
            requires_confirmation=bool(
                payload.get("requires_confirmation", False)
            ),
            reason=str(payload.get("reason") or "")
        )

        if not candidate.content:
            candidate.should_remember = False

        return candidate

    def _fallback_text(self, text, source):
        normalized = text.lower().strip()

        if not normalized:
            return ignored_candidate(source)

        if any(marker in normalized for marker in PREFERENCE_MARKERS):
            return MemoryCandidate(
                should_remember=True,
                kind="preference",
                content=clean_memory_text(text),
                importance=4,
                source=source,
                reason="User expressed a preference."
            )

        if any(marker in normalized for marker in FACT_MARKERS):
            return MemoryCandidate(
                should_remember=True,
                kind="fact",
                content=clean_memory_text(text),
                importance=3,
                source=source,
                reason="User stated a durable fact."
            )

        return ignored_candidate(source)

    def _fallback_event(
        self,
        observation,
        source,
        event_type,
        priority
    ):
        if priority >= 5 or event_type in HIGH_IMPORTANCE_EVENT_TYPES:
            return MemoryCandidate(
                should_remember=True,
                kind="event",
                content=clean_memory_text(observation),
                importance=self._bounded_importance(priority or 5),
                source=source,
                reason="Event priority passed the memory threshold."
            )

        return ignored_candidate(source)

    def _bounded_importance(self, value):
        try:
            value = int(value)
        except (TypeError, ValueError):
            value = 0

        return max(0, min(10, value))


def classify_user_memory(text):
    candidate = MemoryEvaluator().evaluate_text(text)

    if not candidate.should_remember:
        return None

    return {
        "kind": candidate.kind,
        "content": candidate.content,
        "importance": candidate.importance,
        "metadata": candidate.to_memory_kwargs()["metadata"]
    }


def should_store_event(event):
    candidate = MemoryEvaluator().evaluate_event(event)
    return candidate.should_remember


def ignored_candidate(source="unknown"):
    return MemoryCandidate(
        should_remember=False,
        source=source,
        reason="Not important enough for durable memory."
    )


def clean_memory_text(text):
    text = re.sub(r"\s+", " ", str(text))
    return text.strip()
