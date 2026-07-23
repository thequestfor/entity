"""Isolated integration harness for exercising Entity without external writes."""

from dataclasses import dataclass, field

from agent.calendar import CalendarIntentExtractor
from agent.brain.brain import Brain
from agent.confirmations import ConfirmationStore
from agent.lifecycle import Lifecycle
from agent.math_tools import ArithmeticHandler
from agent.memory.store import MemoryStore
from agent.memory import Memory
from agent.planner import AgentPlanner
from agent.policy import Policy
from agent.reminders import ReminderIntentExtractor
from agent.runtime import EntityRuntime


class SnapshotState:
    def __init__(self):
        self.state = {}

    def snapshot(self):
        return dict(self.state)

    def update(self, **values):
        self.state.update(values)

    def record_input(self, text):
        self.state["last_input"] = text

    def record_response(self, text):
        self.state["last_response"] = text


class NoopLearning:
    def observe_action(self, *args, **kwargs):
        return None


class SandboxScheduler:
    def __init__(self, store):
        self.store = store
        self.reminders = []

    def add_reminder_at(
        self,
        due_at,
        message,
        priority=7,
        task_id=None,
        task_kind="reminder"
    ):
        reminder = {
            "due_at": due_at,
            "message": message,
            "priority": priority,
            "task_id": task_id,
            "task_kind": task_kind
        }
        self.reminders.append(reminder)
        return reminder


@dataclass
class SandboxActuator:
    """Records external actions in memory and never performs network writes."""

    fail_actions: set[str] = field(default_factory=set)
    calendar_events: list = field(default_factory=list)
    notifications: list = field(default_factory=list)
    speech: list = field(default_factory=list)

    def can_handle(self, action):
        return action.type in {"calendar", "notify", "speak", "diagnostics"}

    def execute(self, action):
        if action.type in self.fail_actions:
            return None

        if action.type == "calendar":
            draft = action.payload.get("draft")

            if draft is None:
                return None

            self.calendar_events.append(draft)
            return (
                f"Calendar event created: {draft.summary}, "
                f"{draft.start.isoformat()}."
            )

        if action.type == "notify":
            payload = dict(action.payload)
            self.notifications.append(payload)
            return payload.get("text")

        if action.type == "speak":
            stream = action.payload.get("stream")
            text = (
                "".join(stream)
                if stream is not None
                else action.payload.get("text", "")
            )
            self.speech.append(text)
            return text

        return "Sandbox diagnostics passed."


class EntitySandbox:
    def __init__(self, database_path, fail_actions=None):
        self.store = MemoryStore(database_path)
        self.planner = AgentPlanner(store=self.store)
        self.scheduler = SandboxScheduler(self.store)
        self.actuator = SandboxActuator(set(fail_actions or []))
        self.runtime = self._runtime()

    def plan(self, text):
        return self.planner.plan(
            text,
            awareness_state=self.runtime.awareness.snapshot(),
            presence_state=self.runtime.presence.snapshot(),
            capability_context=self.runtime._planner_capability_context(),
            recent_actions=self.runtime.recent_actions,
            recent_responses=self.runtime.recent_responses,
            recent_decisions=self.store.recent_planner_decisions(limit=5)
        )

    def execute(self, text):
        return self.runtime._handle_planned_command(text, source="sandbox")

    def converse(self, text):
        from agent.events import Event

        return self.runtime.handle_text_input(
            Event(
                source="sandbox",
                type="user_speech",
                payload={"text": text}
            ),
            channel="voice"
        )

    def _runtime(self):
        runtime = EntityRuntime.__new__(EntityRuntime)
        runtime.lifecycle = Lifecycle()
        runtime.brain = Brain(memory=Memory(store=self.store))
        runtime.awareness = SnapshotState()
        runtime.presence = SnapshotState()
        runtime.task_store = self.store
        runtime.scheduler_observer = self.scheduler
        runtime.planner = self.planner
        runtime.confirmation_store = ConfirmationStore(store=self.store)
        runtime.calendar_extractor = CalendarIntentExtractor(
            router=self.planner.router
        )
        runtime.reminder_extractor = ReminderIntentExtractor(
            router=self.planner.router
        )
        runtime.arithmetic_handler = ArithmeticHandler()
        runtime.recent_actions = []
        runtime.recent_responses = []
        runtime.actuators = [self.actuator]
        runtime.observers = []
        runtime.policy = Policy()
        runtime.learning_policy = NoopLearning()
        runtime._notify_significant_action = lambda *args, **kwargs: None
        runtime._notify_significant_plan_step = lambda *args, **kwargs: None
        runtime._handle_runtime_command_fallback = (
            lambda *args, **kwargs: None
        )
        return runtime
