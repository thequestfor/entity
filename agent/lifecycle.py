import threading

from agent.events import utc_now


class Lifecycle:
    def __init__(self):
        self._lock = threading.RLock()
        self._sequence = 0
        self._subscribers = []
        self._latest = {
            "sequence": 0,
            "state": "created",
            "timestamp": utc_now(),
            "details": {}
        }

    def emit(self, state, **details):
        with self._lock:
            self._sequence += 1
            event = {
                "sequence": self._sequence,
                "state": str(state),
                "timestamp": utc_now(),
                "details": details
            }
            self._latest = event
            subscribers = list(self._subscribers)

        for subscriber in subscribers:
            try:
                subscriber(dict(event))
            except Exception as exc:
                print("Lifecycle subscriber failed:", exc)

        return event

    def snapshot(self):
        with self._lock:
            return {
                **self._latest,
                "details": dict(self._latest["details"])
            }

    def subscribe(self, callback):
        with self._lock:
            if callback not in self._subscribers:
                self._subscribers.append(callback)

        return callback

    def unsubscribe(self, callback):
        with self._lock:
            if callback in self._subscribers:
                self._subscribers.remove(callback)
