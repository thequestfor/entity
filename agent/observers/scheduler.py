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
    id: str = field(
        default_factory=lambda: str(uuid4()),
        compare=False
    )


class SchedulerObserver:
    def __init__(self):
        self.event_bus = None
        self.running = False
        self.thread = None
        self.condition = threading.Condition()
        self.reminders = []

    def start(self, event_bus):
        self.event_bus = event_bus
        self.running = True
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

    def add_reminder(
        self,
        delay_seconds,
        message,
        priority=7
    ):
        reminder = Reminder(
            due_at=time.time() + delay_seconds,
            message=message,
            priority=priority
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
                    "reminder_id": reminder.id
                },
                priority=reminder.priority
            )
        )
