import queue
import threading

from tts import manager


class TTSStreamer:

    def __init__(self):

        self.queue = queue.Queue()

        self.thread = threading.Thread(
            target=self.worker,
            daemon=True
        )

        self.thread.start()

    def worker(self):

        while True:

            text = self.queue.get()

            print(
                "SPEAKING:",
                text
            )

            if text is None:
                break

            manager.speak(text)

            self.queue.task_done()

    def add(self, text):

        print(
            "QUEUE ADD:",
            text
        )

        self.queue.put(text)


    def wait(self):

        self.queue.join()