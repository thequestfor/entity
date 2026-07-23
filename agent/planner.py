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
    "location",
    "set_voice",
    "arithmetic",
    "briefing",
    "schedule_briefing",
    "learned_knowledge",
    "weather",
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

        return self._ensure_explicit_tools(
            self._validated(payload),
            text
        )

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
            "recent_observations": context.get("recent_observations", []),
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
            "weather when the user asks about conditions, research with "
            "args.notify true when the user wants the result sent after "
            "completion, or create a calendar event when the user wants "
            "something scheduled.\n"
            "- A briefing requested for a future time must use "
            "schedule_briefing with args.time as an ISO datetime and optional "
            "args.wake_text. Do not use briefing or create_reminder for that "
            "future briefing; briefing would run immediately.\n"
            "- Use observers listed in capability context as available input "
            "channels and actuators listed there as available output channels.\n"
            "- Use answer only when no tool is needed.\n"
            "- The planner does not write ordinary conversational answers. "
            "For answer, use empty args and leave response empty so the "
            "conversation model can answer.\n"
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
                    requires_confirmation=(
                        tool not in {"answer", "ask"}
                        and bool(item.get("requires_confirmation", False))
                    )
                )
            )

        response = str(payload.get("response", "")).strip()

        if not steps and response:
            steps.append(
                PlanStep(
                    tool="answer",
                    args={}
                )
            )

        if not steps:
            return None

        for step in steps:
            if step.tool == "answer":
                step.args = {}
            elif step.tool == "ask" and not (
                step.args.get("question") or step.args.get("text")
            ):
                step.args = {"question": response}

        return AgentPlan(
            intent=str(payload.get("intent", "unknown")),
            confidence=confidence,
            steps=steps,
            response="",
            reason=str(payload.get("reason", "")).strip()
        )

    def _ensure_explicit_tools(self, plan, text):
        if plan is None:
            return None

        normalized = text.lower()
        tools = {step.tool for step in plan.steps}
        scheduled_time = self._planned_time(plan.steps)

        if not scheduled_time:
            return plan

        message = self._planned_message(plan.steps) or "Reminder"
        additions = []

        if self._is_scheduled_briefing_request(normalized):
            scheduled_briefing = next(
                (
                    step for step in plan.steps
                    if step.tool == "schedule_briefing"
                ),
                None
            )

            if scheduled_briefing is None:
                reminder = next(
                    (
                        step for step in plan.steps
                        if step.tool == "create_reminder"
                    ),
                    None
                )
                if reminder is not None:
                    reminder.tool = "schedule_briefing"
                    scheduled_briefing = reminder
                else:
                    scheduled_briefing = PlanStep(
                        tool="schedule_briefing",
                        args={"time": scheduled_time}
                    )
                    plan.steps.append(scheduled_briefing)

            scheduled_briefing.args.setdefault("time", scheduled_time)
            scheduled_briefing.args.setdefault("wake_text", "Wake up")
            plan.steps = [
                step for step in plan.steps
                if step.tool != "briefing"
            ]
            tools = {step.tool for step in plan.steps}

        for step in plan.steps:
            if step.tool == "create_reminder":
                step.args.setdefault("text", message)
                step.args.setdefault("time", scheduled_time)
            elif step.tool == "create_calendar_event":
                step.args.setdefault("text", message)

                if not any(
                    step.args.get(name)
                    for name in ("start_time", "start", "date")
                ):
                    step.args["start_time"] = scheduled_time
            elif step.tool == "notify" and "ntfy" in normalized:
                step.args.setdefault("text", message)
                step.args.setdefault("time", scheduled_time)

        if (
            any(phrase in normalized for phrase in (
                "reminder", "remind me", "wake me"
            ))
            and "create_reminder" not in tools
            and "schedule_briefing" not in tools
        ):
            additions.append(
                PlanStep(
                    tool="create_reminder",
                    args={"text": message, "time": scheduled_time}
                )
            )

        if "calendar" in normalized and "create_calendar_event" not in tools:
            additions.append(
                PlanStep(
                    tool="create_calendar_event",
                    args={"text": message, "start_time": scheduled_time}
                )
            )

        if "ntfy" in normalized and "notify" not in tools:
            additions.append(
                PlanStep(
                    tool="notify",
                    args={"text": message, "time": scheduled_time}
                )
            )

        plan.steps.extend(additions)
        return plan

    def _is_scheduled_briefing_request(self, normalized):
        briefing_phrases = (
            "briefing", "morning update", "daily intelligence"
        )
        scheduling_phrases = (
            "wake me", "tomorrow", "tonight", "later", "schedule"
        )
        return (
            any(phrase in normalized for phrase in briefing_phrases)
            and any(phrase in normalized for phrase in scheduling_phrases)
        )

    def _planned_time(self, steps):
        for step in steps:
            date = step.args.get("date")
            clock = step.args.get("time")

            if date and clock and "T" not in str(clock):
                return f"{date}T{clock}"

            for name in ("time", "due_at", "start_time", "start"):
                value = step.args.get(name)

                if value:
                    return str(value)

        return ""

    def _planned_message(self, steps):
        for step in steps:
            for name in ("text", "message", "summary", "title"):
                value = step.args.get(name)

                if value:
                    return str(value)

        return ""

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
