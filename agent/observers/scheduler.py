import heapq
import threading
import time
from dataclasses import dataclass, field
from uuid import uuid4

from agent.events import Event


@dataclass(order=True)
class Reminder:
    due_at: float
    message: str = field(compare=False)
    priority: int = field(default=7, compare=False)
    task_id: str | None = field(default=None, compare=False)
    id: str = field(
        default_factory=lambda: str(uuid4()),
        compare=False
    )


class SchedulerObserver:
    def __init__(self, store=None):
        self.event_bus = None
        self.running = False
        self.thread = None
        self.condition = threading.Condition()
        self.reminders = []
        self.store = store or self._default_store()

    def start(self, event_bus):
        with self.condition:
            if self.running:
                return

            self.event_bus = event_bus
            self.reminders.clear()
            self.running = True

        self._load_pending_tasks()
        self.thread = threading.Thread(
            target=self._run,
            daemon=True
        )
        self.thread.start()

    def stop(self):
        with self.condition:
            self.running = False
            self.condition.notify_all()

        if self.thread:
            self.thread.join(timeout=2)

        self.thread = None

    def add_reminder(
        self,
        delay_seconds,
        message,
        priority=7,
        task_id=None
    ):
        return self.add_reminder_at(
            time.time() + delay_seconds,
            message,
            priority=priority,
            task_id=task_id
        )

    def add_reminder_at(
        self,
        due_at,
        message,
        priority=7,
        task_id=None
    ):
        reminder = Reminder(
            due_at=due_at,
            message=message,
            priority=priority,
            task_id=task_id
        )

        with self.condition:
            heapq.heappush(self.reminders, reminder)
            self.condition.notify_all()

        return reminder

    def _run(self):
        while True:
            with self.condition:
                if not self.running:
                    return

                if not self.reminders:
                    self.condition.wait()
                    continue

                reminder = self.reminders[0]
                wait_seconds = reminder.due_at - time.time()

                if wait_seconds > 0:
                    self.condition.wait(timeout=wait_seconds)
                    continue

                heapq.heappop(self.reminders)

            self._publish(reminder)

    def _publish(self, reminder):
        if not self.event_bus:
            return

        self.event_bus.publish(
            Event(
                source="scheduler",
                type="reminder",
                payload={
                    "message": reminder.message,
                    "reminder_id": reminder.id,
                    "task_id": reminder.task_id
                },
                priority=reminder.priority
            )
        )

    def _load_pending_tasks(self):
        for task in self.store.pending_tasks():
            self.add_reminder_at(
                task["due_at"],
                task["message"],
                priority=task["priority"],
                task_id=task["id"]
            )

    def _default_store(self):
        from agent.memory.store import MemoryStore

        return MemoryStore()
