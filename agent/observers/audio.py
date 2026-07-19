import threading

from agent.events import Event


class AudioObserver:
    def __init__(self, microphone=None):
        self.microphone = microphone or self._default_microphone()
        self.running = False
        self.thread = None

    def start(self, event_bus=None):
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
            event = self.wait_for_event()

            if event and self.event_bus:
                self.event_bus.publish(event)

    def wait_for_event(self):
        self.microphone.wait_for_wake()

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

        return Microphone()
