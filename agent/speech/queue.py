from queue import Queue
from threading import Thread

from tts.manager import speak


class SpeechQueue:

    def __init__(self):

        self.queue = Queue()

        Thread(
            target=self.worker,
            daemon=True
        ).start()

    def worker(self):

        while True:

            sentence = self.queue.get()

            speak(sentence)

            self.queue.task_done()

    def say(self, sentence):

        self.queue.put(sentence)

    def wait(self):

        self.queue.join()
