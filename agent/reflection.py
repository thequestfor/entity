import json
import os
import time

from agent.memory.store import MemoryStore
from agent.models.base import ModelUnavailable
from agent.models.router import ModelRouter


REFLECTION_STATE_KEY = "reflection_last_completed_at"


class PeriodicReflection:
    def __init__(self, store=None, router=None):
        self.store = store or MemoryStore()
        self.router = router or ModelRouter()
        self.enabled = self._env_bool("ENTITY_REFLECTION_ENABLED", True)
        self.interval_seconds = self._env_int(
            "ENTITY_REFLECTION_INTERVAL_SECONDS",
            default=86400,
            minimum=3600
        )

    def due(self):
        if not self.enabled:
            return False

        last_completed = self.store.get_state(REFLECTION_STATE_KEY, 0) or 0

        try:
            last_completed = float(last_completed)
        except (TypeError, ValueError):
            last_completed = 0

        return time.time() - last_completed >= self.interval_seconds

    def reflect(self):
        if not self.enabled:
            return None

        context = self._context()
        reflection = self._model_reflection(context) or self._fallback(context)

        if not reflection:
            self._mark_completed()
            return None

        memory_id = self.store.add_memory(
            kind="reflection",
            content=reflection["content"],
            source="reflection",
            importance=reflection["importance"],
            metadata={
                "confidence": reflection["confidence"],
                "reason": reflection["reason"],
                "source_counts": {
                    "planner_decisions": len(context["planner_decisions"]),
                    "autonomous_goals": len(context["autonomous_goals"]),
                    "conversations": len(context["conversations"]),
                    "pending_tasks": len(context["pending_tasks"])
                }
            }
        )
        self._mark_completed()

        return {
            "memory_id": memory_id,
            **reflection
        }

    def setup_status(self):
        if not self.enabled:
            return "Periodic reflection disabled."

        if self.due():
            return "Periodic reflection online and due."

        return "Periodic reflection online."

    def _context(self):
        return {
            "planner_decisions": self.store.recent_planner_decisions(limit=20),
            "autonomous_goals": self.store.recent_autonomous_goals(limit=20),
            "conversations": self.store.recent_conversations(limit=10),
            "pending_tasks": self.store.pending_tasks()[:10],
            "important_memories": self.store.list_memories(limit=10)
        }

    def _model_reflection(self, context):
        try:
            payload = self.router.generate_json(
                self._prompt(context),
                routing="learning"
            )
        except (ModelUnavailable, ValueError, TypeError, Exception):
            return None

        if not payload.get("should_store", False):
            return None

        content = str(payload.get("content", "")).strip()

        if not content:
            return None

        return {
            "content": content,
            "importance": self._importance(payload.get("importance", 4)),
            "confidence": self._confidence(payload.get("confidence", 0.0)),
            "reason": str(payload.get("reason", "")).strip()
        }

    def _prompt(self, context):
        return (
            "You are Entity's periodic reflection process. Review recent "
            "planner decisions, autonomous goals, conversations, pending "
            "tasks, and memories. Store at most one concise reflection that "
            "would help Entity behave better later. Do not store mundane "
            "activity, secrets, or unsupported assumptions. Return JSON only.\n\n"
            "Return exactly this JSON shape:\n"
            "{\n"
            '  "should_store": true,\n'
            '  "content": "short durable reflection",\n'
            '  "importance": 4,\n'
            '  "confidence": 0.75,\n'
            '  "reason": "short reason"\n'
            "}\n\n"
            f"Context: {json.dumps(context, default=str)}"
        )

    def _fallback(self, context):
        failed = [
            item
            for item in context["planner_decisions"]
            if item.get("outcome") in {"fallback_used", "canceled", "failed"}
        ]

        if failed:
            outcome = failed[0].get("outcome", "unknown")
            intent = failed[0].get("intent", "unknown")
            return {
                "content": (
                    "Entity recently had a planner decision with outcome "
                    f"{outcome} for intent {intent}; similar future requests "
                    "should use that failure as planning context."
                ),
                "importance": 4,
                "confidence": 0.65,
                "reason": "Fallback reflection from recent planner failures."
            }

        pending = context["pending_tasks"]

        if pending:
            return {
                "content": (
                    f"Entity has {len(pending)} pending task(s); future "
                    "planning should account for existing obligations before "
                    "adding more reminders."
                ),
                "importance": 3,
                "confidence": 0.6,
                "reason": "Fallback reflection from pending tasks."
            }

        return None

    def _mark_completed(self):
        self.store.set_state(REFLECTION_STATE_KEY, time.time())

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

    def _env_bool(self, name, default=False):
        value = os.getenv(name)

        if value is None:
            return default

        return value.lower().strip() in {
            "1",
            "true",
            "yes",
            "on"
        }

    def _env_int(self, name, default, minimum):
        try:
            value = int(os.getenv(name, str(default)))
        except ValueError:
            value = default

        return max(minimum, value)
