print("BOOT")

from agent.runtime import EntityRuntime
from tts.manager import set_voice


set_voice("kokoro")


def run_entity():
    EntityRuntime().run()


if __name__ == "__main__":
    run_entity()
