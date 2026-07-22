from agent.speech.buffer import SentenceBuffer
from agent.speech.queue import SpeechQueue


buffer = SentenceBuffer()

queue = SpeechQueue()


def stream_text(token):

    for sentence in buffer.add(token):

        queue.say(sentence)


def stream_phrase(phrase):
    phrase = str(phrase or "").strip()

    if phrase:
        queue.say(phrase)


def flush():

    for sentence in buffer.flush():

        queue.say(sentence)


def wait():

    queue.wait()


def say(text):

    queue.say(text)

    wait()
