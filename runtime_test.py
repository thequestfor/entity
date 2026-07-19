from agent.events import Event
from agent.runtime import EntityRuntime


class FakeBrain:
    def respond_stream(self, command, state):
        yield "Hello "
        yield command


class FakeAwareness:
    def __init__(self):
        self.inputs = []
        self.responses = []

    def start(self):
        pass

    def stop(self):
        pass

    def snapshot(self):
        return {
            "mode": "test"
        }

    def record_input(self, text):
        self.inputs.append(text)

    def record_response(self, text):
        self.responses.append(text)


class FakeAudioObserver:
    def __init__(self, event=None):
        self.event = event
        self.started = False

    def start(self, event_bus):
        self.started = True

        if self.event:
            event_bus.publish(self.event)

    def stop(self):
        pass


class FakeSpeechActuator:
    def __init__(self):
        self.spoken = []

    def can_handle(self, action):
        return action.type == "speak"

    def execute(self, action):
        stream = action.payload.get("stream")

        if stream is not None:
            text = "".join(stream)
        else:
            text = action.payload.get("text", "")

        self.spoken.append(text)

        return text


awareness = FakeAwareness()
speech = FakeSpeechActuator()

runtime = EntityRuntime(
    brain=FakeBrain(),
    awareness=awareness,
    observers=[
        FakeAudioObserver()
    ],
    actuators=[speech]
)

result = runtime.handle_event(
    Event(
        source="test",
        type="user_speech",
        payload={
            "text": "Ben"
        },
        priority=5
    )
)

assert result == "Hello Ben"
assert awareness.inputs == ["Ben"]
assert awareness.responses == ["Hello Ben"]
assert speech.spoken == ["Hello Ben"]

bus_awareness = FakeAwareness()
bus_speech = FakeSpeechActuator()
bus_observer = FakeAudioObserver(
    Event(
        source="test",
        type="user_speech",
        payload={
            "text": "Bus"
        },
        priority=5
    )
)
bus_runtime = EntityRuntime(
    brain=FakeBrain(),
    awareness=bus_awareness,
    observers=[
        bus_observer
    ],
    actuators=[
        bus_speech
    ]
)

bus_runtime.start()
event = bus_runtime.event_bus.next_event()
bus_runtime.handle_event(event)
bus_runtime.event_bus.task_done()
bus_runtime.stop()

assert bus_observer.started
assert bus_awareness.inputs == ["Bus"]
assert bus_awareness.responses == ["Hello Bus"]
assert bus_speech.spoken == [
    "Systems online",
    "Hello Bus"
]

reminder_awareness = FakeAwareness()
reminder_speech = FakeSpeechActuator()
reminder_runtime = EntityRuntime(
    brain=FakeBrain(),
    awareness=reminder_awareness,
    observers=[
        FakeAudioObserver()
    ],
    actuators=[
        reminder_speech
    ]
)

reminder_result = reminder_runtime.handle_event(
    Event(
        source="test",
        type="user_speech",
        payload={
            "text": "remind me in 1 second to stretch"
        },
        priority=5
    )
)

assert reminder_result == "Reminder set: stretch."
assert reminder_awareness.inputs == [
    "remind me in 1 second to stretch"
]
assert reminder_awareness.responses == [
    "Reminder set: stretch."
]
assert reminder_speech.spoken == [
    "Reminder set: stretch."
]

print("runtime event path ok")
