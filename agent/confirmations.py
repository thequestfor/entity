import time
from dataclasses import asdict
from uuid import uuid4

from agent.memory.store import MemoryStore


CONFIRMATION_STATE_KEY = "pending_confirmation"


class ConfirmationStore:
    def __init__(self, store=None, ttl_seconds=600):
        self.store = store or MemoryStore()
        self.ttl_seconds = ttl_seconds

    def create(self, plan, original_text, source="user", decision_id=None):
        pending = {
            "id": str(uuid4()),
            "decision_id": decision_id,
            "original_text": original_text,
            "source": source,
            "plan": self._plan_payload(plan),
            "created_at": time.time(),
            "expires_at": time.time() + self.ttl_seconds
        }
        self.store.set_state(CONFIRMATION_STATE_KEY, pending)
        return pending

    def current(self):
        pending = self.store.get_state(CONFIRMATION_STATE_KEY)

        if not pending:
            return None

        if self._expired(pending):
            self.clear()
            return None

        return pending

    def clear(self):
        self.store.set_state(CONFIRMATION_STATE_KEY, None)

    def count(self):
        return 1 if self.current() else 0

    def setup_status(self):
        count = self.count()

        if count:
            return "Confirmation flow online. Pending confirmations: 1."

        return "Confirmation flow online. No pending confirmations."

    def _expired(self, pending):
        try:
            return time.time() > float(pending.get("expires_at", 0))
        except (TypeError, ValueError):
            return True

    def _plan_payload(self, plan):
        return {
            "intent": plan.intent,
            "confidence": plan.confidence,
            "response": plan.response,
            "reason": plan.reason,
            "steps": [
                asdict(step)
                for step in plan.steps
            ]
        }
