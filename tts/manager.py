from tts import kokoro
from tts import sam


VOICE = "kokoro"


def set_voice(name: str):

    global VOICE
    VOICE = name


def speak(text: str):

    if VOICE == "kokoro":

        kokoro.speak(text)

    elif VOICE == "sam":

        sam.speak(text)

    else:

        raise ValueError(
            f"Unknown voice: {VOICE}"
        )