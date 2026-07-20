import os
import threading
import time

from agent.confirmations import ConfirmationStore
from agent.events import Event
from agent.goals import AutonomousGoalPolicy
from agent.health import StartupHealthCheck
from agent.memory.store import MemoryStore
from agent.reflection import PeriodicReflection


class AutonomyObserver:
    def __init__(
        self,
        store=None,
        health_check=None,
        confirmation_store=None,
        goal_policy=None,
        reflection=None
    ):
        self.store = store or MemoryStore()
        self.health_check = health_check or StartupHealthCheck()
        self.confirmation_store = (
            confirmation_store or ConfirmationStore(store=self.store)
        )
        self.goal_policy = goal_policy or AutonomousGoalPolicy(
            store=self.store
        )
        self.reflection = reflection or PeriodicReflection(store=self.store)
        self.event_bus = None
        self.running = False
        self.thread = None
        self.enabled = self._env_bool("ENTITY_AUTONOMY_ENABLED", default=True)
        self.poll_seconds = self._env_int(
            "ENTITY_AUTONOMY_POLL_SECONDS",
            default=900,
            minimum=60
        )
        self.initial_delay = self._env_int(
            "ENTITY_AUTONOMY_INITIAL_DELAY_SECONDS",
            default=60,
            minimum=0
        )
        self.alert_repeat_seconds = self._env_int(
            "ENTITY_AUTONOMY_ALERT_REPEAT_SECONDS",
            default=3600,
            minimum=300
        )

    def start(self, event_bus):
        self.event_bus = event_bus

        if not self.enabled:
            return

        self.running = True
        self.thread = threading.Thread(
            target=self._run,
            daemon=True
        )
        self.thread.start()

    def stop(self):
        self.running = False

        if self.thread:
            self.thread.join(timeout=2)

    def setup_status(self):
        if not self.enabled:
            return "Autonomous self-maintenance disabled."

        return (
            "Autonomous self-maintenance online. "
            f"Poll interval: {self.poll_seconds} seconds. "
            + self.goal_policy.setup_status()
            + " "
            + self.reflection.setup_status()
        )

    def _run(self):
        self._sleep(self.initial_delay)

        while self.running:
            try:
                self._poll()
            except Exception as exc:
                print("Autonomy observer error:", exc)

            self._sleep(self.poll_seconds)

    def _poll(self):
        health_issues = self.health_check.issues()
        pending_confirmation = self.confirmation_store.current()
        goal = self.goal_policy.choose(
            health_issues=health_issues,
            pending_confirmation=pending_confirmation,
            presence_state=self.store.get_state("presence", default={}) or {},
            pending_tasks=self.store.pending_tasks(),
            recent_decisions=self.store.recent_planner_decisions(limit=5),
            recent_goals=self.store.recent_autonomous_goals(limit=10),
            reflection_due=self.reflection.due()
        )

        self.store.add_autonomous_goal(
            name=goal.name,
            priority=goal.priority,
            message=goal.message,
            reason=goal.reason,
            confidence=goal.confidence,
            outcome="selected",
            metadata={
                "notify": goal.notify,
                "speak": goal.speak,
                "store_reflection": goal.store_reflection
            }
        )

        if goal.name == "stay_idle":
            self._set_last_signature("")
            return

        signature = self._signature(goal, pending_confirmation)

        if not self._should_publish(signature):
            return

        self._set_last_signature(signature)
        self._set_last_published_at(time.time())

        self.event_bus.publish(
            Event(
                source="autonomy",
                type="autonomous_goal",
                payload={
                    "message": goal.message,
                    "goal": goal.to_dict(),
                    "health_issues": health_issues,
                    "pending_confirmation": bool(pending_confirmation)
                },
                priority=goal.priority
            )
        )

    def _should_publish(self, signature):
        if signature != self._last_signature():
            return True

        last_published_at = self._last_published_at()

        if not last_published_at:
            return True

        return time.time() - last_published_at >= self.alert_repeat_seconds

    def _signature(self, goal, pending_confirmation):
        pending_id = ""

        if pending_confirmation:
            pending_id = pending_confirmation.get("id", "")

        return "|".join(
            [
                goal.name,
                goal.message,
                f"pending_confirmation:{pending_id}"
            ]
        )

    def _last_signature(self):
        return self.store.get_state("autonomy_last_signature", "") or ""

    def _set_last_signature(self, value):
        self.store.set_state("autonomy_last_signature", value)

    def _last_published_at(self):
        return self.store.get_state("autonomy_last_published_at", 0) or 0

    def _set_last_published_at(self, value):
        self.store.set_state("autonomy_last_published_at", value)

    def _sleep(self, seconds):
        deadline = time.time() + seconds

        while self.running and time.time() < deadline:
            time.sleep(min(1, deadline - time.time()))

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
