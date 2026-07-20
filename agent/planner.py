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
            "Allowed tools:\n"
            "- answer: reply with text only.\n"
            "- ask: ask a follow-up question because required details are missing.\n"
            "- diagnostics: run system diagnostics.\n"
            "- set_presence: args may include location and availability.\n"
            "- set_voice: args.voice must be kokoro or sam.\n"
            "- arithmetic: calculate a simple arithmetic expression from the input.\n"
            "- briefing: build today's briefing.\n"
            "- research: args.query is the web search query.\n"
            "- research_and_remember: search and store sourced useful facts.\n"
            "- remember_last_research: store the most recent research result.\n"
            "- create_calendar_event: schedule a calendar event from the user's text.\n"
            "- create_reminder: create a reminder from the user's text.\n"
            "- store_memory: args.kind and args.content store an explicit memory.\n"
            "- behavior_feedback: learn explicit feedback about Entity's behavior.\n\n"
            "Rules:\n"
            "- If the user asks for diagnostics/status, choose diagnostics.\n"
            "- If the user asks to calculate arithmetic, choose arithmetic.\n"
            "- If the user asks to schedule or put something on a calendar, "
            "choose create_calendar_event.\n"
            "- If the user asks to be reminded, choose create_reminder.\n"
            "- If the user says research/look up/search/find online, choose "
            "research unless they also say remember, then choose "
            "research_and_remember.\n"
            "- If the user says remember what you found, choose "
            "remember_last_research.\n"
            "- If the user gives explicit feedback like too late, ask me next "
            "time, don't do that, or that was helpful, choose behavior_feedback.\n"
            "- If the user explicitly says remember that, choose store_memory.\n"
            "- Use ask when essential details are missing.\n"
            "- Set requires_confirmation true for destructive, external, or "
            "uncertain actions. Creating normal reminders and calendar events "
            "can be false when confidence is high.\n\n"
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
