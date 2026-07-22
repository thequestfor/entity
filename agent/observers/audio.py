import threading
import time

from agent.audio.activity import is_speaking
from agent.events import Event


class AudioObserver:
    def __init__(self, microphone=None, on_state=None):
        self.on_state = on_state
        self.microphone = microphone or self._default_microphone()
        self.running = False
        self.thread = None

    def start(self, event_bus=None):
        if self.running:
            return

        self.event_bus = event_bus
        self.running = True
        self.microphone.start()

        if event_bus:
            self.thread = threading.Thread(
                target=self._run,
                daemon=True
            )
            self.thread.start()

    def stop(self):
        self.running = False
        self.microphone.stop()

        if self.thread:
            self.thread.join(timeout=2)

    def _run(self):
        while self.running:
            if is_speaking():
                time.sleep(0.05)
                continue

            try:
                if not self.microphone.running:
                    self._emit_state("recovering", component="microphone")
                    self.microphone.start()

                event = self.wait_for_event()
            except Exception as exc:
                self._emit_state(
                    "error",
                    component="audio",
                    message=str(exc)
                )
                time.sleep(2)
                continue

            if event and self.event_bus:
                self.event_bus.publish(event)
            elif self.running:
                self._emit_state("idle")

    def wait_for_event(self):
        if not self.microphone.wait_for_wake():
            return None

        self._emit_state("wake_detected")
        self._emit_state("listening")
        command = self.microphone.listen()

        if not command:
            return None

        return Event(
            source="microphone",
            type="user_speech",
            payload={
                "text": command,
                "message": command
            },
            priority=5
        )

    def _default_microphone(self):
        from agent.audio.microphone import Microphone

        return Microphone(on_state=self._emit_state)

    def _emit_state(self, state, **details):
        if self.on_state:
            self.on_state(state, **details)
