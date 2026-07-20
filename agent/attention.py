import json
from dataclasses import asdict, dataclass

from agent.models.base import ModelUnavailable
from agent.models.router import ModelRouter


VALID_DECISIONS = {
    "ignore",
    "remember",
    "notify",
    "ask",
    "act"
}


@dataclass
class ImportanceDecision:
    decision: str = "ignore"
    importance: float = 0.0
    urgency: float = 0.0
    reason: str = ""
    should_remember: bool = False
    should_notify: bool = False
    requires_confirmation: bool = False
    question: str = ""
    mode: str = "fallback"
    provider: str | None = None

    def to_dict(self):
        return asdict(self)


class ImportancePolicy:
    def __init__(
        self,
        router=None,
        notify_threshold=0.8,
        remember_threshold=0.55
    ):
        self.router = router or ModelRouter()
        self.notify_threshold = notify_threshold
        self.remember_threshold = remember_threshold

    def evaluate(self, event, awareness_state=None, memory_context=None):
        provider = self.router.provider()

        if provider is None:
            return self._fallback(event)

        try:
            payload = self.router.generate_json(
                self._prompt(event, awareness_state, memory_context),
                temperature=0
            )
            return self._validated(payload, provider.name)
        except (ModelUnavailable, json.JSONDecodeError, KeyError, TypeError):
            return self._fallback(event)

    def model_health_decision(self):
        provider = self.router.provider()

        if provider is not None:
            return ImportanceDecision(
                decision="ignore",
                importance=0.0,
                urgency=0.0,
                reason=f"Language model available through {provider.name}.",
                mode="model-health",
                provider=provider.name
            )

        return ImportanceDecision(
            decision="notify",
            importance=1.0,
            urgency=0.95,
            reason=(
                "No language model is available. Entity is operating in "
                "limited deterministic mode."
            ),
            should_notify=True,
            requires_confirmation=False,
            mode="model-health",
            provider=None
        )

    def status(self):
        provider = self.router.provider()

        if provider is None:
            return {
                "mode": "fallback",
                "provider": None
            }

        return {
            "mode": "model",
            "provider": provider.name
        }

    def _prompt(self, event, awareness_state, memory_context):
        event_payload = event.to_dict()
        context = {
            "awareness": awareness_state or {},
            "memory_context": memory_context or {}
        }

        return (
            "You are Entity's importance policy. Decide what should happen "
            "with the observed event. Return JSON only. Allowed decisions are "
            "ignore, remember, notify, ask, and act. The runtime will validate "
            "your output before doing anything.\n\n"
            "Rules:\n"
            "- Notify Ben for urgent, time-sensitive, safety-related, or "
            "system-health events.\n"
            "- Remember useful stable facts, preferences, commitments, and "
            "important observations.\n"
            "- Ask only when a short clarifying question would resolve useful "
            "uncertainty.\n"
            "- Act only for explicit user requests or already-approved safe "
            "runtime actions.\n"
            "- Do not notify for ordinary chatter or low-confidence noise.\n\n"
            "Return exactly this JSON shape:\n"
            "{\n"
            '  "decision": "ignore|remember|notify|ask|act",\n'
            '  "importance": 0.0,\n'
            '  "urgency": 0.0,\n'
            '  "reason": "short reason",\n'
            '  "should_remember": false,\n'
            '  "should_notify": false,\n'
            '  "requires_confirmation": false,\n'
            '  "question": ""\n'
            "}\n\n"
            f"Event:\n{json.dumps(event_payload, indent=2)}\n\n"
            f"Context:\n{json.dumps(context, indent=2)}"
        )

    def _validated(self, payload, provider_name):
        decision = str(payload.get("decision", "ignore")).lower().strip()

        if decision not in VALID_DECISIONS:
            decision = "ignore"

        importance = self._clamp(payload.get("importance", 0.0))
        urgency = self._clamp(payload.get("urgency", 0.0))
        should_notify = bool(payload.get("should_notify", False))
        should_remember = bool(payload.get("should_remember", False))

        if importance >= self.notify_threshold or urgency >= self.notify_threshold:
            should_notify = True

        if importance >= self.remember_threshold:
            should_remember = True

        if decision == "notify":
            should_notify = True

        if decision == "remember":
            should_remember = True

        return ImportanceDecision(
            decision=decision,
            importance=importance,
            urgency=urgency,
            reason=str(payload.get("reason", "")).strip(),
            should_remember=should_remember,
            should_notify=should_notify,
            requires_confirmation=bool(
                payload.get("requires_confirmation", False)
            ),
            question=str(payload.get("question", "")).strip(),
            mode="model",
            provider=provider_name
        )

    def _fallback(self, event):
        if event.type == "reminder":
            return ImportanceDecision(
                decision="notify",
                importance=0.9,
                urgency=0.9,
                reason="A scheduled reminder is due.",
                should_remember=True,
                should_notify=True,
                mode="fallback"
            )

        if event.type in {"remote_message", "user_speech"}:
            return ImportanceDecision(
                decision="act",
                importance=0.65,
                urgency=0.4,
                reason="Ben directly addressed Entity.",
                should_remember=True,
                should_notify=False,
                mode="fallback"
            )

        if event.priority >= 8:
            return ImportanceDecision(
                decision="notify",
                importance=0.85,
                urgency=0.8,
                reason="The event priority is high.",
                should_remember=True,
                should_notify=True,
                mode="fallback"
            )

        return ImportanceDecision(
            decision="ignore",
            importance=0.2,
            urgency=0.1,
            reason="No high-confidence reason to interrupt Ben.",
            should_remember=False,
            should_notify=False,
            mode="fallback"
        )

    def _clamp(self, value):
        try:
            value = float(value)
        except (TypeError, ValueError):
            value = 0.0

        return min(1.0, max(0.0, value))


class Attention:
    def __init__(self):
        self.threshold = 5

    def should_interrupt(self, event):
        return event.priority >= self.threshold
