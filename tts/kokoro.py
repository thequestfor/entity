import tempfile
import subprocess

import soundfile as sf

from kokoro import KPipeline


pipeline = KPipeline(
    lang_code="a"
)


VOICE = "af_heart"


def speak(text):

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


        subprocess.run(
            [
                "afplay",
                f.name
            ],
            check=True
        )