import re

from agent.actuators import DiagnosticsActuator, SpeechActuator
from agent.awareness import AwarenessLoop
from agent.event_bus import EventBus
from agent.events import Action
from agent.observers import AudioObserver, SchedulerObserver
from agent.policy import Policy


class EntityRuntime:
    def __init__(
        self,
        brain=None,
        awareness=None,
        audio_observer=None,
        scheduler_observer=None,
        observers=None,
        actuators=None,
        policy=None
    ):
        self.brain = brain or self._default_brain()
        self.awareness = awareness or AwarenessLoop(
            on_interrupt=self.publish_event
        )
        self.event_bus = EventBus()
        self.scheduler_observer = (
            scheduler_observer or SchedulerObserver()
        )
        self.observers = observers or [
            self.scheduler_observer,
            audio_observer or AudioObserver()
        ]
        self.actuators = actuators or [
            DiagnosticsActuator(),
            SpeechActuator()
        ]
        self.policy = policy or Policy()

    def run(self):
        self.start()

        try:
            while True:
                event = self.event_bus.next_event()

                if event:
                    self.handle_event(event)

                self.event_bus.task_done()

        finally:
            self.stop()

    def start(self):
        self.awareness.start()

        for observer in self.observers:
            observer.start(self.event_bus)

        self.execute(
            Action(
                type="speak",
                payload={
                    "text": "Systems online"
                }
            )
        )

    def stop(self):
        self.awareness.stop()

        for observer in self.observers:
            observer.stop()

    def publish_event(self, event):
        self.event_bus.publish(event)

    def handle_event(self, event):
        if event.type == "user_speech":
            return self.handle_user_speech(event)

        if event.message:
            return self.execute(
                Action(
                    type="speak",
                    payload={
                        "text": event.message
                    }
                )
            )

        return None

    def _default_brain(self):
        from agent.brain import Brain

        return Brain()

    def handle_user_speech(self, event):
        command = event.payload.get("text", "")

        if not command:
            return None

        print("Heard:", command)

        self.awareness.record_input(command)

        runtime_response = self._handle_runtime_command(command)

        if runtime_response:
            self.awareness.record_response(runtime_response)
            print(runtime_response)
            return runtime_response

        action = Action(
            type="speak",
            payload={
                "stream": self.brain.respond_stream(
                    command,
                    self.awareness.snapshot()
                )
            }
        )

        response = self.execute(action)

        self.awareness.record_response(response)

        print(response)

        return response

    def _handle_runtime_command(self, command):
        if self._is_diagnostics_command(command):
            report = self.execute(
                Action(
                    type="diagnostics",
                    payload={
                        "runtime": self
                    }
                )
            )

            self.execute(
                Action(
                    type="speak",
                    payload={
                        "text": report
                    }
                )
            )

            return report

        voice_response = self._handle_voice_command(command)

        if voice_response:
            return voice_response

        reminder = self._parse_reminder(command)

        if not reminder:
            return None

        delay_seconds, message = reminder

        self.scheduler_observer.add_reminder(
            delay_seconds,
            message
        )

        response = f"Reminder set: {message}."

        self.execute(
            Action(
                type="speak",
                payload={
                    "text": response
                }
            )
        )

        return response

    def _parse_reminder(self, command):
        pattern = re.compile(
            r"\bremind me in (\d+)\s+"
            r"(second|seconds|minute|minutes|hour|hours)"
            r"(?:\s+to\s+(.+))?",
            re.IGNORECASE
        )
        match = pattern.search(command)

        if not match:
            return None

        amount = int(match.group(1))
        unit = match.group(2).lower()
        message = (match.group(3) or "Reminder").strip()

        multiplier = 1

        if unit.startswith("minute"):
            multiplier = 60
        elif unit.startswith("hour"):
            multiplier = 3600

        return amount * multiplier, message

    def _handle_voice_command(self, command):
        normalized = command.lower().strip()

        if (
            "what voice" in normalized
            or "which voice" in normalized
            or "current voice" in normalized
        ):
            from tts.manager import get_voice

            response = f"Current voice: {get_voice()}."

            self.execute(
                Action(
                    type="speak",
                    payload={
                        "text": response
                    }
                )
            )

            return response

        pattern = re.compile(
            r"\b(?:use|switch to|set|change to)\s+"
            r"(?:the\s+)?(kokoro|sam)"
            r"(?:\s+voice)?\b",
            re.IGNORECASE
        )
        match = pattern.search(command)

        if not match:
            return None

        voice = match.group(1).lower()

        from tts.manager import set_voice

        set_voice(voice)

        response = f"Voice set to {voice}."

        self.execute(
            Action(
                type="speak",
                payload={
                    "text": response
                }
            )
        )

        return response

    def _is_diagnostics_command(self, command):
        normalized = command.lower()

        return (
            "diagnostic" in normalized
            or "system status" in normalized
            or "status report" in normalized
        )

    def execute(self, action):
        if not self.policy.allows(action):
            print(
                "Action blocked by policy:",
                action.type
            )
            return None

        for actuator in self.actuators:
            if actuator.can_handle(action):
                return actuator.execute(action)

        print(
            "No actuator for action:",
            action.type
        )

        return None
