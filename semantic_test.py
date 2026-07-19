from agent.events import Event
from agent.memory.semantic import MemoryEvaluator


evaluator = MemoryEvaluator()

preference = evaluator.evaluate_text(
    "Remember that I prefer concise answers."
)

assert preference.should_remember
assert preference.kind == "preference"
assert preference.importance >= 4

mundane = evaluator.evaluate_text(
    "The light is on."
)

assert not mundane.should_remember

security_event = evaluator.evaluate_event(
    Event(
        source="camera",
        type="unknown_person",
        payload={
            "message": "Unknown person detected near the desk."
        },
        priority=7
    )
)

assert security_event.should_remember
assert security_event.kind == "event"
assert security_event.importance == 7

print("semantic evaluator fallback ok")
