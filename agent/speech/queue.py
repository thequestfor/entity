from queue import Empty, Queue
from threading import Event, Thread

from tts.manager import speak


class SpeechQueue:
    def __init__(self, speaker=None, on_error=None):
        self.queue = Queue()
        self.speaker = speaker or speak
        self.on_error = on_error
        self.errors = Queue()
        self.stopped = Event()
        self.sentinel = object()
        self.thread = Thread(
            target=self.worker,
            daemon=True
        )
        self.thread.start()

    def worker(self):
        while True:
            sentence = self.queue.get()

            try:
                if sentence is self.sentinel:
                    return

                self.speaker(sentence)
            except Exception as exc:
                self.errors.put(exc)

                if self.on_error:
                    self.on_error(exc)
            finally:
                self.queue.task_done()

    def say(self, sentence):
        if self.stopped.is_set():
            raise RuntimeError("Speech queue is stopped.")

        self.queue.put(sentence)

    def wait(self):
        self.queue.join()

        failures = []

        while True:
            try:
                failures.append(self.errors.get_nowait())
            except Empty:
                break

        if failures:
            raise RuntimeError(
                f"Speech playback failed: {failures[-1]}"
            ) from failures[-1]

    def stop(self, timeout=2):
        if self.stopped.is_set():
            return

        self.stopped.set()
        self.queue.put(self.sentinel)
        self.thread.join(timeout=timeout)
