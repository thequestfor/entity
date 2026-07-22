import threading
from contextlib import contextmanager


_speaking = threading.Event()
_output_lock = threading.RLock()
_output_subscribers = []


def is_speaking():
    return _speaking.is_set()


@contextmanager
def speaking():
    _speaking.set()

    try:
        yield
    finally:
        _speaking.clear()


def emit_speech_output_activity(level):
    try:
        normalized = min(1.0, max(0.0, float(level)))
    except (TypeError, ValueError):
        return

    with _output_lock:
        subscribers = list(_output_subscribers)

    for subscriber in subscribers:
        try:
            subscriber(normalized)
        except Exception:
            pass


@contextmanager
def speech_output_listener(callback):
    if callback is None:
        yield
        return

    with _output_lock:
        if callback not in _output_subscribers:
            _output_subscribers.append(callback)

    try:
        yield
    finally:
        with _output_lock:
            if callback in _output_subscribers:
                _output_subscribers.remove(callback)
