from pathlib import Path
import subprocess
import tempfile

from agent.utils.text import chunk_tts

SAM = Path(__file__).parent.parent / "engines" / "sam"


def speak(text: str):

    for chunk in chunk_tts(text):

        with tempfile.NamedTemporaryFile(suffix=".wav") as audio:

            subprocess.run(
                [
                    str(SAM),
                    "-wav",
                    audio.name,
                    chunk
                ],
                check=True
            )

            subprocess.run(
                [
                    "afplay",
                    audio.name
                ],
                check=True
            )
