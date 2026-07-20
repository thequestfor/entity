import json
import os
import time
from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

from agent.models.base import ModelUnavailable
from agent.models.router import ModelRouter


ALLOWED_GOALS = {
    "stay_idle",
    "monitor_service_health",
    "follow_up_pending_confirmation",
    "prepare_today_briefing",
    "review_failed_tool",
    "suggest_memory_review",
    "periodic_reflection"
}


@dataclass
class AutonomousGoal:
    name: str
    priority: int = 1
    message: str = ""
    reason: str = ""
    confidence: float = 0.0
    notify: bool = False
    speak: bool = False
    store_reflection: bool = False

    def to_dict(self):
        return {
            "name": self.name,
            "priority": self.priority,
            "message": self.message,
            "reason": self.reason,
            "confidence": self.confidence,
            "notify": self.notify,
            "speak": self.speak,
            "store_reflection": self.store_reflection
        }


class AutonomousGoalPolicy:
    def __init__(self, router=None, store=None):
        self.router = router or ModelRouter()
        self.store = store
        self.enabled = self._env_bool("ENTITY_AUTONOMOUS_GOALS_ENABLED", True)

    def choose(
        self,
        health_issues=None,
        pending_confirmation=None,
        presence_state=None,
        pending_tasks=None,
        recent_decisions=None,
        recent_goals=None,
        reflection_due=False
    ):
        if not self.enabled:
            return idle_goal("Autonomous goal selection disabled.")

        context = {
            "current_local_datetime": self._now(),
            "health_issues": health_issues or [],
            "pending_confirmation": bool(pending_confirmation),
            "presence": presence_state or {},
            "pending_tasks": (pending_tasks or [])[:5],
            "recent_decisions": (recent_decisions or [])[:5],
            "recent_goals": (recent_goals or [])[:10],
            "reflection_due": bool(reflection_due)
        }

        goal = self._model_goal(context)

        if goal:
            return goal

        return self._fallback_goal(context)

    def setup_status(self):
        if not self.enabled:
            return "Autonomous goal selection disabled."

        return "Autonomous goal selection online."

    def _model_goal(self, context):
        try:
            payload = self.router.generate_json(
                self._prompt(context),
                routing="learning"
            )
        except (ModelUnavailable, ValueError, TypeError, Exception):
            return None

        return self._validated(payload)

    def _prompt(self, context):
        return (
            "You are Entity's autonomous goal selector. Choose one safe "
            "internal goal for Entity to care about right now. Entity is "
            "allowed to notify Ben, speak if presence allows, store a "
            "low-risk reflection, or stay idle. Entity is not allowed to "
            "create calendar events, change settings, control devices, or "
            "browse the web autonomously in this version. Return JSON only.\n\n"
            "Allowed goals: stay_idle, monitor_service_health, "
            "follow_up_pending_confirmation, prepare_today_briefing, "
            "review_failed_tool, suggest_memory_review, "
            "periodic_reflection.\n\n"
            "Rules:\n"
            "- Choose stay_idle when there is nothing useful to do.\n"
            "- Choose monitor_service_health for missing critical services.\n"
            "- Choose follow_up_pending_confirmation when an action is waiting.\n"
            "- Choose review_failed_tool when recent planner decisions show "
            "failed, fallback, canceled, or unavailable tool outcomes.\n"
            "- Choose prepare_today_briefing only when timing and presence make "
            "a briefing useful.\n"
            "- Choose periodic_reflection when reflection_due is true and no "
            "higher-priority health or confirmation issue exists.\n"
            "- Keep messages short and concrete.\n\n"
            "Return exactly this JSON shape:\n"
            "{\n"
            '  "name": "stay_idle",\n'
            '  "priority": 1,\n'
            '  "message": "",\n'
            '  "reason": "short reason",\n'
            '  "confidence": 0.0,\n'
            '  "notify": false,\n'
            '  "speak": false,\n'
            '  "store_reflection": false\n'
            "}\n\n"
            f"Context: {json.dumps(context, default=str)}"
        )

    def _validated(self, payload):
        name = str(payload.get("name", "stay_idle")).strip()

        if name not in ALLOWED_GOALS:
            name = "stay_idle"

        confidence = self._confidence(payload.get("confidence", 0.0))

        if confidence < 0.5:
            return None

        return AutonomousGoal(
            name=name,
            priority=self._priority(payload.get("priority", 1)),
            message=str(payload.get("message", "")).strip(),
            reason=str(payload.get("reason", "")).strip(),
            confidence=confidence,
            notify=bool(payload.get("notify", False)),
            speak=bool(payload.get("speak", False)),
            store_reflection=bool(payload.get("store_reflection", False))
        )

    def _fallback_goal(self, context):
        health_issues = context["health_issues"]

        if health_issues:
            return AutonomousGoal(
                name="monitor_service_health",
                priority=8,
                message=(
                    "Autonomous maintenance found service issues. "
                    + " ".join(health_issues)
                ),
                reason="Critical service health issues are present.",
                confidence=0.85,
                notify=True,
                speak=True
            )

        if context["pending_confirmation"]:
            return AutonomousGoal(
                name="follow_up_pending_confirmation",
                priority=6,
                message="A pending action is still waiting for confirmation.",
                reason="Entity should follow up on unresolved pending actions.",
                confidence=0.8,
                notify=True,
                speak=True
            )

        failed = self._recent_failed_decision(context["recent_decisions"])

        if failed:
            return AutonomousGoal(
                name="review_failed_tool",
                priority=5,
                message=(
                    "I noticed a recent tool decision did not complete cleanly."
                ),
                reason=(
                    "Recent planner outcome was "
                    f"{failed.get('outcome', 'unknown')}."
                ),
                confidence=0.7,
                notify=False,
                speak=False,
                store_reflection=True
            )

        if context["reflection_due"]:
            return AutonomousGoal(
                name="periodic_reflection",
                priority=4,
                message="Periodic reflection is due.",
                reason="The reflection interval elapsed.",
                confidence=0.75,
                notify=False,
                speak=False,
                store_reflection=False
            )

        if self._briefing_makes_sense(context):
            return AutonomousGoal(
                name="prepare_today_briefing",
                priority=4,
                message="Preparing today's briefing.",
                reason="Morning briefing window is active.",
                confidence=0.65,
                notify=False,
                speak=True
            )

        return idle_goal("No useful autonomous goal right now.")

    def _recent_failed_decision(self, decisions):
        failed_outcomes = {
            "fallback_used",
            "canceled",
            "failed"
        }

        for decision in decisions:
            if decision.get("outcome") in failed_outcomes:
                return decision

        return None

    def _briefing_makes_sense(self, context):
        presence = context.get("presence") or {}

        if presence.get("availability") in {"sleeping", "do_not_disturb"}:
            return False

        hour = datetime.fromisoformat(
            context["current_local_datetime"]
        ).hour

        if hour < 6 or hour > 10:
            return False

        for goal in context.get("recent_goals", []):
            if goal.get("name") == "prepare_today_briefing":
                return False

        return True

    def _now(self):
        timezone = ZoneInfo(
            os.getenv("ENTITY_TIMEZONE", "America/New_York")
        )
        return datetime.now(timezone).isoformat()

    def _priority(self, value):
        try:
            value = int(value)
        except (TypeError, ValueError):
            value = 1

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


def idle_goal(reason):
    return AutonomousGoal(
        name="stay_idle",
        priority=1,
        reason=reason,
        confidence=1.0
    )
