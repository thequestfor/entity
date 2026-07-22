import argparse
import os

import dotenv

from agent.runtime import EntityRuntime
from agent.visual import VISUAL_MODES, create_visual_sink
from tts.manager import set_voice


dotenv.load_dotenv()

set_voice(
    os.getenv("ENTITY_TTS_VOICE", "kokoro")
)


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Run Entity with a selected visual interface."
    )
    parser.add_argument(
        "visual",
        nargs="?",
        choices=VISUAL_MODES,
        default=os.getenv("ENTITY_VISUAL_MODE", "2d").lower(),
        help="visual interface: 2d, 3d, or unreal (default: 2d)"
    )
    args = parser.parse_args(argv)
    if args.visual not in VISUAL_MODES:
        parser.error(
            "ENTITY_VISUAL_MODE must be one of: "
            + ", ".join(VISUAL_MODES)
        )
    return args


def run_entity(visual_mode=None):
    mode = visual_mode or parse_args().visual
    print(f"BOOT: visual={mode}")
    EntityRuntime(visual_sink=create_visual_sink(mode)).run()


if __name__ == "__main__":
    run_entity()
