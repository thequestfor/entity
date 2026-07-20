import json
import re
from dataclasses import dataclass

from agent.memory.semantic import clean_memory_text
from agent.memory.store import MemoryStore
from agent.models.base import ModelUnavailable
from agent.models.router import ModelRouter


@dataclass
class BehaviorFeedback:
    should_store: bool
    content: str = ""
    trigger: str = "general"
    polarity: str = "neutral"
    importance: int = 6
    confidence: float = 0.0
    reason: str = ""


class BehaviorFeedbackPolicy:
    def __init__(self, store=None, router=None):
        self.store = store or MemoryStore()
        self.router = router or ModelRouter()

    def handle_feedback(
        self,
        text,
        recent_actions=None,
        recent_responses=None,
        source="user"
    ):
        if not self._looks_like_feedback(text):
            return None

        feedback = self._feedback_from_model(
            text,
            recent_actions=recent_actions or [],
            recent_responses=recent_responses or []
        )

        if feedback is None:
            feedback = self._fallback_feedback(text)

        if not feedback or not feedback.should_store:
            return "I heard the feedback, but I do not have enough context to turn it into a behavior rule."

        memory_id = self._store_feedback(
            feedback,
            text,
            recent_actions=recent_actions or [],
            recent_responses=recent_responses or [],
            source=source
        )

        if not memory_id:
            return "I already have that behavior rule stored."

        return f"Behavior rule stored: {feedback.content}"

    def setup_status(self):
        return "Behavior feedback learning online."

    def _looks_like_feedback(self, text):
        normalized = text.lower().strip()

        phrases = [
            "that was helpful",
            "that helped",
            "good job",
            "that was good",
            "don't do that",
            "do not do that",
            "dont do that",
            "stop doing that",
            "ask me next time",
            "ask before",
            "you should have",
            "you should not have",
            "too early",
            "too late",
            "that was wrong",
            "that was right",
            "use the thinking model",
            "use cloud",
            "don't notify me",
            "do not notify me",
            "notify me for that"
        ]

        return any(phrase in normalized for phrase in phrases)

    def _feedback_from_model(
        self,
        text,
        recent_actions=None,
        recent_responses=None
    ):
        try:
            payload = self.router.generate_json(
                self._prompt(text, recent_actions, recent_responses),
                user_input=text,
                routing="learning"
            )
        except (ModelUnavailable, ValueError, TypeError, Exception):
            return None

        feedback = BehaviorFeedback(
            should_store=bool(payload.get("should_store", False)),
            content=clean_memory_text(payload.get("content", "")),
            trigger=str(payload.get("trigger", "general")),
            polarity=str(payload.get("polarity", "neutral")),
            importance=self._importance(payload.get("importance", 6)),
            confidence=self._confidence(payload.get("confidence", 0.0)),
            reason=str(payload.get("reason", ""))
        )

        if not feedback.content or feedback.confidence < 0.65:
            feedback.should_store = False

        return feedback

    def _prompt(self, text, recent_actions=None, recent_responses=None):
        context = {
            "recent_actions": self._safe_context(recent_actions or []),
            "recent_responses": self._safe_context(recent_responses or [])
        }

        return (
            "You are Entity's behavior feedback learner. Convert Ben's "
            "explicit feedback into one durable behavior rule if possible. "
            "The rule should guide future choices, notification behavior, "
            "model escalation, scheduling, reminders, or asking for "
            "confirmation. Do not store vague praise unless it identifies a "
            "behavior to repeat. Return JSON only.\n\n"
            "Return exactly this JSON shape:\n"
            "{\n"
            '  "should_store": true,\n'
            '  "content": "When ..., Entity should ...",\n'
            '  "trigger": "calendar|reminder|notification|speech|model_escalation|general",\n'
            '  "polarity": "positive|negative|correction",\n'
            '  "importance": 7,\n'
            '  "confidence": 0.8,\n'
            '  "reason": "short reason"\n'
            "}\n\n"
            f"Feedback: {text}\n"
            f"Context: {json.dumps(context)}"
        )

    def _fallback_feedback(self, text):
        normalized = text.lower().strip()

        rules = [
            (
                ("ask me next time", "ask before"),
                "When an action could change Ben's calendar, reminders, notifications, or external services, Entity should ask before doing it.",
                "general",
                "correction",
                8
            ),
            (
                ("don't notify me", "do not notify me", "dont notify me"),
                "Entity should avoid notifying Ben for similar low-priority events unless they are urgent or explicitly requested.",
                "notification",
                "negative",
                7
            ),
            (
                ("notify me for that",),
                "Entity should notify Ben for similar events when he is away from the speaker.",
                "notification",
                "positive",
                7
            ),
            (
                ("too early",),
                "Entity should schedule similar reminders or departure alerts later unless there is a clear reason to warn early.",
                "reminder",
                "correction",
                7
            ),
            (
                ("too late",),
                "Entity should schedule similar reminders or departure alerts earlier so Ben has more time to act.",
                "reminder",
                "correction",
                8
            ),
            (
                ("use the thinking model",),
                "Entity should escalate similar complex or error-prone requests to the local thinking model.",
                "model_escalation",
                "correction",
                8
            ),
            (
                ("use cloud",),
                "Entity should consider cloud AI for similar requests when local models are uncertain or unavailable.",
                "model_escalation",
                "correction",
                7
            ),
            (
                ("don't do that", "do not do that", "dont do that", "stop doing that"),
                "Entity should avoid repeating the most recent behavior without checking with Ben first.",
                "general",
                "negative",
                8
            ),
            (
                ("that was helpful", "that helped", "good job", "that was good"),
                "Entity should prefer repeating the most recent helpful behavior in similar situations.",
                "general",
                "positive",
                5
            )
        ]

        for phrases, content, trigger, polarity, importance in rules:
            if any(phrase in normalized for phrase in phrases):
                return BehaviorFeedback(
                    should_store=True,
                    content=content,
                    trigger=trigger,
                    polarity=polarity,
                    importance=importance,
                    confidence=0.7,
                    reason="Fallback rule from explicit feedback phrase."
                )

        if re.search(r"\byou should\b", normalized):
            return BehaviorFeedback(
                should_store=True,
                content=clean_memory_text(text),
                trigger="general",
                polarity="correction",
                importance=6,
                confidence=0.65,
                reason="Feedback contains an explicit instruction."
            )

        return BehaviorFeedback(should_store=False)

    def _store_feedback(
        self,
        feedback,
        original_text,
        recent_actions=None,
        recent_responses=None,
        source="user"
    ):
        if self._has_exact_rule(feedback.content):
            return None

        return self.store.add_memory(
            kind="behavior_rule",
            content=feedback.content,
            source="feedback",
            importance=feedback.importance,
            metadata={
                "trigger": feedback.trigger,
                "polarity": feedback.polarity,
                "confidence": feedback.confidence,
                "reason": feedback.reason,
                "feedback_text": original_text,
                "feedback_source": source,
                "recent_actions": self._safe_context(recent_actions or []),
                "recent_responses": self._safe_context(recent_responses or [])
            }
        )

    def _has_exact_rule(self, content):
        normalized = content.lower().strip()

        for memory in self.store.search(content, limit=5):
            if (
                memory["kind"] == "behavior_rule"
                and memory["content"].lower().strip() == normalized
            ):
                return True

        return False

    def _safe_context(self, items):
        safe_items = []

        for item in items[-5:]:
            try:
                safe_items.append(
                    json.loads(json.dumps(item, default=str))
                )
            except TypeError:
                safe_items.append(str(item))

        return safe_items

    def _importance(self, value):
        try:
            value = int(value)
        except (TypeError, ValueError):
            value = 6

        return min(10, max(1, value))

    def _confidence(self, value):
        try:
            value = float(value)
        except (TypeError, ValueError):
            value = 0.0

        return min(1.0, max(0.0, value))
