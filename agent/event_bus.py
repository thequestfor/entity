from queue import Empty, Queue


class EventBus:
    def __init__(self):
        self.queue = Queue()

    def publish(self, event):
        self.queue.put(event)

    def next_event(self, timeout=None):
        return self.queue.get(timeout=timeout)

    def task_done(self):
        self.queue.task_done()

    def empty(self):
        return self.queue.empty()

    def drain(self):
        events = []

        while True:
            try:
                events.append(self.queue.get_nowait())
                self.queue.task_done()
            except Empty:
                break

        return events
