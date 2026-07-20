import tempfile

import soundfile as sf

from agent.utils.text import sanitize_tts
from kokoro import KPipeline
from tts.playback import play_wav


pipeline = KPipeline(
    lang_code="a"
)


VOICE = "af_heart"


def speak(text):
    text = sanitize_tts(text)

    if not text:
        return

    audio_chunks = []


    generator = pipeline(
        text,
        voice=VOICE
    )


    for _, _, audio in generator:

        audio_chunks.append(audio)


    if not audio_chunks:
        return


    import numpy as np

    full_audio = np.concatenate(
        audio_chunks
    )


    with tempfile.NamedTemporaryFile(
        suffix=".wav"
    ) as f:

        sf.write(
            f.name,
            full_audio,
            24000
        )


        play_wav(f.name)
