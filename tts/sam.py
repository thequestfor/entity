import os
from pathlib import Path
import subprocess
import tempfile

from agent.utils.text import chunk_tts
from tts.playback import play_wav

DEFAULT_SAM = Path(__file__).parent.parent / "engines" / "sam"


def sam_binary():
    return Path(
        os.getenv("ENTITY_SAM_PATH") or DEFAULT_SAM
    )


def speak(text: str):
    sam = sam_binary()

    if not sam.exists():
        raise RuntimeError(
            "SAM voice is selected, but no SAM binary was found. "
            "Set ENTITY_SAM_PATH to the SAM executable."
        )

    for chunk in chunk_tts(text):

        with tempfile.NamedTemporaryFile(suffix=".wav") as audio:

            subprocess.run(
                [
                    str(sam),
                    "-wav",
                    audio.name,
                    chunk
                ],
                check=True
            )

            play_wav(audio.name)
