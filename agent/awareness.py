import threading
import time
from datetime import datetime

from agent.attention import Attention


class AwarenessLoop:
    def __init__(
        self,
        interval=2.0,
        observers=None,
        on_interrupt=None
    ):
        self.interval = interval
        self.observers = observers or []
        self.on_interrupt = on_interrupt
        self.attention = Attention()

        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._thread = None
        self._last_input_at = None

        self._state = {
            "mode": "normal",
            "activity": "idle",
            "user_present": True,
            "priority": 0,
            "last_input": None,
            "last_response": None,
            "last_awareness_tick": None,
            "seconds_since_input": None
        }

    def start(self):
        if self._thread and self._thread.is_alive():
            return

        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run,
            daemon=True
        )
        self._thread.start()

    def stop(self):
        self._stop.set()

        if self._thread:
            self._thread.join(timeout=2)

    def snapshot(self):
        with self._lock:
            return dict(self._state)

    def record_input(self, text):
        now = time.time()

        with self._lock:
            self._last_input_at = now
            self._state["last_input"] = text
            self._state["activity"] = "listening"
            self._state["seconds_since_input"] = 0

    def record_response(self, text):
        with self._lock:
            self._state["last_response"] = text
            self._state["activity"] = "speaking"

    def _run(self):
        while not self._stop.is_set():
            self.tick()
            self._stop.wait(self.interval)

    def tick(self):
        events = []

        with self._lock:
            now = time.time()
            self._state["last_awareness_tick"] = datetime.now().isoformat(
                timespec="seconds"
            )

            if self._last_input_at is None:
                self._state["seconds_since_input"] = None
            else:
                self._state["seconds_since_input"] = int(
                    now - self._last_input_at
                )

            if self._state["activity"] in {"listening", "speaking"}:
                self._state["activity"] = "idle"

            state = dict(self._state)

        for observer in self.observers:
            event = observer(state)

            if event:
                events.append(event)

        for event in events:
            if self.attention.should_interrupt(event):
                with self._lock:
                    self._state["priority"] = event.priority

                if self.on_interrupt:
                    self.on_interrupt(event)
