from agent.event_bus import EventBus
from agent.observers.scheduler import SchedulerObserver


bus = EventBus()
scheduler = SchedulerObserver()

scheduler.start(bus)
scheduler.add_reminder(
    0.01,
    "Check the test reminder."
)

event = bus.next_event(timeout=1)
bus.task_done()
scheduler.stop()

assert event.source == "scheduler"
assert event.type == "reminder"
assert event.message == "Check the test reminder."
assert event.priority == 7

print("scheduler observer ok")
