import threading
from contextlib import contextmanager


_speaking = threading.Event()


def is_speaking():
    return _speaking.is_set()


@contextmanager
def speaking():
    _speaking.set()

    try:
        yield
    finally:
        _speaking.clear()
