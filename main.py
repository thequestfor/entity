print("BOOT")

import os

import dotenv

from agent.runtime import EntityRuntime
from tts.manager import set_voice


dotenv.load_dotenv()

set_voice(
    os.getenv("ENTITY_TTS_VOICE", "kokoro")
)


def run_entity():
    EntityRuntime().run()


if __name__ == "__main__":
    run_entity()
