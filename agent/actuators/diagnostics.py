import importlib.util
import os

import dotenv

from agent.models.cloud_openai import CloudOpenAIProvider
from agent.models.ollama import OllamaProvider


class DiagnosticsActuator:
    action_type = "diagnostics"

    def can_handle(self, action):
        return action.type == self.action_type

    def execute(self, action):
        dotenv.load_dotenv()

        runtime = action.payload.get("runtime")
        lines = [
            "System diagnostic complete."
        ]

        lines.extend(self._model_status())
        lines.extend(self._tts_status())
        lines.extend(self._memory_status())
        lines.extend(self._runtime_status(runtime))
        lines.extend(self._dependency_status())

        return " ".join(lines)

    def _model_status(self):
        local = OllamaProvider()
        cloud = CloudOpenAIProvider()
        lines = []

        if local.available():
            lines.append(
                f"Local language model online: {local.model}."
            )
            if local.think:
                lines.append("Local model thinking enabled.")
            else:
                lines.append("Local model thinking disabled.")
        elif local.enabled:
            lines.append(
                "Local language model configured but unavailable."
            )
        else:
            lines.append(
                "Local language model not configured."
            )

        if cloud.available():
            lines.append(
                f"Cloud AI available: {cloud.model}."
            )
        elif cloud.enabled:
            if not os.getenv("OPENAI_API_KEY"):
                lines.append(
                    "Cloud AI enabled but missing API key."
                )
            elif importlib.util.find_spec("openai") is None:
                lines.append(
                    "Cloud AI enabled but OpenAI client is missing."
                )
            else:
                lines.append(
                    "Cloud AI enabled but unavailable."
                )
        else:
            lines.append(
                "Cloud AI disabled."
            )

        if local.available():
            lines.append("Using local AI.")
        elif cloud.available():
            lines.append("Using cloud AI.")
        else:
            lines.append("No language model is currently available.")

        return lines

    def _tts_status(self):
        voice = os.getenv("ENTITY_TTS_VOICE", "kokoro")

        if voice == "sam":
            from tts.sam import sam_binary

            if sam_binary().exists():
                return [
                    "TTS voice selected: SAM. SAM binary available."
                ]

            return [
                "TTS voice selected: SAM. SAM binary unavailable."
            ]

        return [
            f"TTS voice selected: {voice}."
        ]

    def _memory_status(self):
        try:
            from agent.memory.store import MemoryStore

            store = MemoryStore()

            with store._connect() as conn:
                conn.execute("SELECT 1").fetchone()

            return [
                "Memory database online."
            ]
        except Exception as exc:
            return [
                f"Memory database unavailable: {exc}."
            ]

    def _runtime_status(self, runtime):
        if runtime is None:
            return [
                "Runtime status unavailable."
            ]

        lines = [
            "Event bus online."
        ]

        awareness_state = runtime.awareness.snapshot()

        if awareness_state.get("last_awareness_tick"):
            lines.append("Awareness loop online.")
        else:
            lines.append("Awareness loop started, awaiting first tick.")

        for observer in runtime.observers:
            name = observer.__class__.__name__
            running = getattr(observer, "running", None)

            if running is True:
                lines.append(f"{name} online.")
            elif running is False:
                lines.append(f"{name} offline.")
            else:
                lines.append(f"{name} status unknown.")

        return lines

    def _dependency_status(self):
        checks = {
            "Wake word": "openwakeword",
            "Speech recognition": "faster_whisper",
            "Voice activity detection": "silero_vad",
            "Audio input": "sounddevice",
            "Audio files": "soundfile",
            "TTS": "kokoro",
            "OpenAI client": "openai"
        }
        missing = [
            label
            for label, module in checks.items()
            if importlib.util.find_spec(module) is None
        ]

        if not missing:
            return [
                "Runtime dependencies available."
            ]

        return [
            "Missing dependencies: "
            + ", ".join(missing)
            + "."
        ]
