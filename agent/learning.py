import json
from dataclasses import dataclass

from agent.events import Action, Event
from agent.memory.semantic import clean_memory_text
from agent.memory.store import MemoryStore
from agent.models.base import ModelUnavailable
from agent.models.router import ModelRouter


LEARNABLE_EVENT_TYPES = {
    "user_speech",
    "remote_message",
    "reminder",
    "calendar_event_upcoming"
}

LEARNABLE_ACTION_TYPES = {
    "calendar"
}


@dataclass
class LearningCandidate:
    should_remember: bool
    kind: str = "pattern"
    content: str = ""
    importance: int = 4
    confidence: float = 0.0
    reason: str = ""


class LearningPolicy:
    def __init__(self, store=None, router=None):
        self.store = store or MemoryStore()
        self.router = router or ModelRouter()

    def observe_event(self, event, awareness_state=None, presence_state=None):
        if event.type not in LEARNABLE_EVENT_TYPES:
            return None

        candidate = self._candidate_from_model(
            subject=event.to_dict(),
            source="event",
            awareness_state=awareness_state,
            presence_state=presence_state
        )

        if candidate is None:
            candidate = self._fallback_event(event)

        return self._store_candidate(candidate, event.id, "event")

    def observe_action(self, action, awareness_state=None, presence_state=None):
        if action.type not in LEARNABLE_ACTION_TYPES:
            return None

        candidate = self._candidate_from_model(
            subject=action.to_dict(),
            source="action",
            awareness_state=awareness_state,
            presence_state=presence_state
        )

        if candidate is None:
            candidate = self._fallback_action(action)

        return self._store_candidate(candidate, action.id, "action")

    def _candidate_from_model(
        self,
        subject,
        source,
        awareness_state=None,
        presence_state=None
    ):
        try:
            payload = self.router.generate_json(
                self._prompt(
                    subject,
                    source,
                    awareness_state,
                    presence_state
                ),
                routing="learning"
            )
            return self._validated(payload)
        except (
            ModelUnavailable,
            ValueError,
            TypeError,
            KeyError,
            json.JSONDecodeError,
            Exception
        ):
            return None

    def _prompt(
        self,
        subject,
        source,
        awareness_state=None,
        presence_state=None
    ):
        context = {
            "awareness": awareness_state or {},
            "presence": (
                presence_state.to_dict()
                if hasattr(presence_state, "to_dict")
                else presence_state or {}
            )
        }

        return (
            "You are Entity's autonomous learning policy. Decide whether an "
            "event or action contains a durable lesson about Ben's routines, "
            "preferences, common places, commitments, or useful patterns. "
            "Do not store mundane one-off chatter, secrets, or invasive "
            "observations. Prefer concise summaries. Return JSON only.\n\n"
            "Return exactly this JSON shape:\n"
            "{\n"
            '  "should_remember": false,\n'
            '  "kind": "fact|preference|routine|pattern|place|task",\n'
            '  "content": "short memory sentence",\n'
            '  "importance": 0,\n'
            '  "confidence": 0.0,\n'
            '  "reason": "short reason"\n'
            "}\n\n"
            f"Source: {source}\n"
            f"Context: {json.dumps(context)}\n"
            f"Observed: {json.dumps(subject)}"
        )

    def _validated(self, payload):
        candidate = LearningCandidate(
            should_remember=bool(payload.get("should_remember", False)),
            kind=str(payload.get("kind", "pattern")),
            content=clean_memory_text(payload.get("content", "")),
            importance=self._importance(payload.get("importance", 4)),
            confidence=self._confidence(payload.get("confidence", 0.0)),
            reason=str(payload.get("reason", ""))
        )

        if not candidate.content or candidate.confidence < 0.7:
            candidate.should_remember = False

        return candidate

    def _fallback_event(self, event):
        if event.type in {"user_speech", "remote_message"}:
            text = event.payload.get("text", "")
            normalized = text.lower()

            if "remember that" in normalized or normalized.startswith("remember "):
                return LearningCandidate(
                    should_remember=True,
                    kind="fact",
                    content=clean_memory_text(text),
                    importance=5,
                    confidence=0.75,
                    reason="Ben explicitly asked Entity to remember this."
                )

        if event.type == "calendar_event_upcoming":
            summary = event.payload.get("summary", "")
            location = event.payload.get("location", "")

            if summary and location:
                return LearningCandidate(
                    should_remember=True,
                    kind="routine",
                    content=(
                        f"Ben has {summary} at {location} as a calendar "
                        "event."
                    ),
                    importance=5,
                    confidence=0.75,
                    reason="Calendar event includes a stable title and location."
                )

        if event.type == "reminder":
            message = event.payload.get("message", "")

            if message:
                return LearningCandidate(
                    should_remember=True,
                    kind="task",
                    content=f"Ben asked to be reminded: {message}.",
                    importance=3,
                    confidence=0.7,
                    reason="Reminder may indicate a recurring task or concern."
                )

        return ignored_learning()

    def _fallback_action(self, action):
        if action.type == "calendar":
            draft = action.payload.get("draft")

            if draft and getattr(draft, "recurrence", None):
                location = f" at {draft.location}" if draft.location else ""

                return LearningCandidate(
                    should_remember=True,
                    kind="routine",
                    content=(
                        f"Ben has {draft.summary}{location} as a recurring "
                        "calendar event."
                    ),
                    importance=6,
                    confidence=0.8,
                    reason="Created recurring calendar event."
                )

        return ignored_learning()

    def _store_candidate(self, candidate, source_id, source_kind):
        if not candidate or not candidate.should_remember:
            return None

        if self._has_similar_memory(candidate.content):
            return None

        return self.store.add_memory(
            kind=candidate.kind,
            content=candidate.content,
            source="learning",
            importance=candidate.importance,
            metadata={
                "confidence": candidate.confidence,
                "reason": candidate.reason,
                "source_id": source_id,
                "source_kind": source_kind
            }
        )

    def _has_similar_memory(self, content):
        normalized = content.lower().strip()
        memories = self.store.search(content, limit=5)

        for memory in memories:
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


def ignored_learning():
    return LearningCandidate(
        should_remember=False,
        reason="No durable lesson found."
    )
