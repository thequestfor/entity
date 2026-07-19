AVAILABLE_VOICES = {
    "kokoro",
    "sam"
}

VOICE = "kokoro"


def set_voice(name: str):
    name = name.lower().strip()

    if name not in AVAILABLE_VOICES:
        raise ValueError(
            f"Unknown voice: {name}"
        )

    global VOICE
    VOICE = name


def get_voice():
    return VOICE


def available_voices():
    return sorted(AVAILABLE_VOICES)


def speak(text: str):

    if VOICE == "kokoro":
        from tts import kokoro

        kokoro.speak(text)

    elif VOICE == "sam":
        from tts import sam

        sam.speak(text)

    else:

        raise ValueError(
            f"Unknown voice: {VOICE}"
        )
