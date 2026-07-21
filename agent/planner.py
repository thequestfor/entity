import json
from dataclasses import dataclass, field
from datetime import datetime
from zoneinfo import ZoneInfo

from agent.memory.store import MemoryStore
from agent.models.base import ModelUnavailable
from agent.models.router import ModelRouter


ALLOWED_TOOLS = {
    "answer",
    "ask",
    "diagnostics",
    "set_presence",
    "set_voice",
    "arithmetic",
    "briefing",
    "notify",
    "research",
    "research_and_remember",
    "remember_last_research",
    "create_calendar_event",
    "create_reminder",
    "store_memory",
    "behavior_feedback"
}


@dataclass
class PlanStep:
    tool: str
    args: dict = field(default_factory=dict)
    requires_confirmation: bool = False


@dataclass
class AgentPlan:
    intent: str
    confidence: float
    steps: list[PlanStep] = field(default_factory=list)
    response: str = ""
    reason: str = ""

    @classmethod
    def from_dict(cls, payload):
        return cls(
            intent=str(payload.get("intent", "unknown")),
            confidence=float(payload.get("confidence", 0.0)),
            response=str(payload.get("response", "")),
            reason=str(payload.get("reason", "")),
            steps=[
                PlanStep(
                    tool=str(item.get("tool", "")),
                    args=item.get("args") or {},
                    requires_confirmation=bool(
                        item.get("requires_confirmation", False)
                    )
                )
                for item in payload.get("steps", [])
                if isinstance(item, dict)
            ]
        )


class AgentPlanner:
    def __init__(self, router=None, store=None):
        self.router = router or ModelRouter()
        self.store = store or MemoryStore()

    def plan(
        self,
        text,
        awareness_state=None,
        presence_state=None,
        capability_context=None,
        recent_actions=None,
        recent_responses=None,
        recent_decisions=None,
        on_escalation=None
    ):
        try:
            payload = self.router.generate_json(
                self._prompt(
                    text,
                    awareness_state=awareness_state,
                    presence_state=presence_state,
                    capability_context=capability_context,
                    recent_actions=recent_actions or [],
                    recent_responses=recent_responses or [],
                    recent_decisions=recent_decisions or []
                ),
                user_input=text,
                on_escalation=on_escalation,
                routing="planner"
            )
        except (ModelUnavailable, ValueError, TypeError, Exception):
            return None

        return self._validated(payload)

    def setup_status(self):
        return "LLM-directed action planner online."

    def _prompt(
        self,
        text,
        awareness_state=None,
        presence_state=None,
        capability_context=None,
        recent_actions=None,
        recent_responses=None,
        recent_decisions=None
    ):
        context = self.store.recall_context(text, limit=6)
        now = datetime.now(self._timezone()).isoformat()
        presence = (
            presence_state.to_dict()
            if hasattr(presence_state, "to_dict")
            else presence_state or {}
        )
        behavior_rules = [
            {
                "content": item["content"],
                "importance": item["importance"],
                "metadata": item["metadata"]
            }
            for item in context.get("relevant_memories", [])
            if item.get("kind") == "behavior_rule"
        ]
        payload = {
            "current_local_datetime": now,
            "awareness": awareness_state or {},
            "presence": presence,
            "capabilities": capability_context or {},
            "behavior_rules": behavior_rules,
            "relevant_memories": context.get("relevant_memories", []),
            "recent_actions": recent_actions[-5:],
            "recent_responses": recent_responses[-5:],
            "recent_decisions": recent_decisions[-5:]
        }

        return (
            "You are Entity's LLM action planner. Choose what Entity should "
            "do with the user's input. You do not directly call APIs; you "
            "return a structured plan for Python to validate and execute. "
            "Prefer local tools over general chat when a tool applies. "
            "Use behavior rules when relevant. Use recent decisions and "
            "tool outcomes to avoid repeating failed choices, stale claims, "
            "or canceled actions. Return JSON only.\n\n"
            "Planning model:\n"
            "- Read the user's actual intent, then choose the smallest useful "
            "set of tools from the capability context.\n"
            "- Compose tools when the user asks for a workflow. For example, "
            "research with args.notify true when the user wants the result "
            "sent after completion, or create a calendar event when the user "
            "wants something scheduled.\n"
            "- Use observers listed in capability context as available input "
            "channels and actuators listed there as available output channels.\n"
            "- Use answer only when no tool is needed.\n"
            "- Use ask when essential details are missing.\n"
            "- Use behavior rules, memory, recent decisions, and recent "
            "tool outcomes to adapt. Avoid repeating failed or unwanted "
            "behavior.\n"
            "- Set requires_confirmation true for destructive, high-risk, "
            "external, or uncertain actions. Low-risk normal reminders and "
            "calendar events can be false when confidence is high.\n\n"
            "Return exactly this JSON shape:\n"
            "{\n"
            '  "intent": "short_intent_name",\n'
            '  "confidence": 0.0,\n'
            '  "reason": "short reason",\n'
            '  "response": "text to say if useful",\n'
            '  "steps": [\n'
            "    {\n"
            '      "tool": "answer",\n'
            '      "requires_confirmation": false,\n'
            '      "args": {}\n'
            "    }\n"
            "  ]\n"
            "}\n\n"
            f"Context: {json.dumps(payload, default=str)}\n"
            f"User input: {text}"
        )

    def _validated(self, payload):
        confidence = self._confidence(payload.get("confidence", 0.0))

        if confidence < 0.4:
            return None

        steps = []

        for item in payload.get("steps", []):
            if not isinstance(item, dict):
                continue

            tool = str(item.get("tool", "")).strip()

            if tool not in ALLOWED_TOOLS:
                continue

            args = item.get("args") or {}

            if not isinstance(args, dict):
                args = {}

            steps.append(
                PlanStep(
                    tool=tool,
                    args=args,
                    requires_confirmation=bool(
                        item.get("requires_confirmation", False)
                    )
                )
            )

        response = str(payload.get("response", "")).strip()

        if not steps and response:
            steps.append(
                PlanStep(
                    tool="answer",
                    args={
                        "text": response
                    }
                )
            )

        if not steps:
            return None

        return AgentPlan(
            intent=str(payload.get("intent", "unknown")),
            confidence=confidence,
            steps=steps,
            response=response,
            reason=str(payload.get("reason", "")).strip()
        )

    def _timezone(self):
        import os

        return ZoneInfo(
            os.getenv("ENTITY_TIMEZONE", "America/New_York")
        )

    def _confidence(self, value):
        try:
            value = float(value)
        except (TypeError, ValueError):
            value = 0.0

        return min(1.0, max(0.0, value))
