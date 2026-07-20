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
        lines.extend(self._notification_status())
        lines.extend(self._calendar_status())
        lines.extend(self._route_status())
        lines.extend(self._research_status())
        lines.extend(self._research_memory_status(runtime))
        lines.extend(self._startup_health_status(runtime))
        lines.extend(self._presence_status(runtime))
        lines.extend(self._planner_status(runtime))
        lines.extend(self._confirmation_status(runtime))
        lines.extend(self._autonomous_goal_status(runtime))
        lines.extend(self._learning_status(runtime))
        lines.extend(self._behavior_feedback_status(runtime))
        lines.extend(self._memory_status())
        lines.extend(self._importance_status(runtime))
        lines.extend(self._runtime_status(runtime))
        lines.extend(self._dependency_status())

        return " ".join(lines)

    def _model_status(self):
        local = OllamaProvider(name="local_fast", think=False)
        local_thinking = OllamaProvider(
            name="local_thinking",
            model=os.getenv(
                "ENTITY_LOCAL_REASONING_LLM_MODEL",
                os.getenv("ENTITY_LOCAL_LLM_MODEL")
            ),
            think=True,
            enabled=local.enabled
        )
        cloud = CloudOpenAIProvider()
        lines = []

        if local.available():
            lines.append(
                f"Fast local language model online: {local.model}."
            )
            lines.append("Fast local model thinking disabled.")
        elif local.enabled:
            lines.append(
                "Fast local language model configured but unavailable."
            )
        else:
            lines.append(
                "Local language model not configured."
            )

        if local_thinking.available():
            lines.append(
                f"Local thinking model online: {local_thinking.model}."
            )
        elif local.enabled:
            lines.append(
                "Local thinking model configured but unavailable."
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
            lines.append("Default route: fast local AI.")
        elif local_thinking.available():
            lines.append("Default route: local thinking AI.")
        elif cloud.available():
            lines.append("Default route: cloud AI.")
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

    def _notification_status(self):
        provider = os.getenv("ENTITY_NOTIFY_PROVIDER", "").lower()
        base_url = os.getenv("ENTITY_NTFY_URL", "https://ntfy.sh")
        out_topic = os.getenv("ENTITY_NTFY_OUT_TOPIC", "")
        in_topic = os.getenv("ENTITY_NTFY_IN_TOPIC", "")

        if provider != "ntfy":
            return [
                "Plaintext notifications disabled."
            ]

        lines = [
            f"Plaintext notifications configured through ntfy at {base_url}."
        ]

        if out_topic:
            lines.append("Outbound plaintext topic configured.")
        else:
            lines.append("Outbound plaintext topic missing.")

        if in_topic:
            lines.append("Inbound plaintext topic configured.")
        else:
            lines.append("Inbound plaintext topic missing.")

        return lines

    def _calendar_status(self):
        try:
            from agent.calendar import GoogleCalendarClient

            return [
                GoogleCalendarClient().setup_status()
            ]
        except Exception as exc:
            return [
                f"Google Calendar status unavailable: {exc}."
            ]

    def _route_status(self):
        try:
            from agent.routes import RoutePlanner

            return [
                RoutePlanner().setup_status()
            ]
        except Exception as exc:
            return [
                f"Route planning status unavailable: {exc}."
            ]

    def _research_status(self):
        try:
            from agent.research import ResearchTool

            return [
                ResearchTool().setup_status()
            ]
        except Exception as exc:
            return [
                f"Internet research status unavailable: {exc}."
            ]

    def _research_memory_status(self, runtime):
        if runtime is None or not hasattr(runtime, "research_memory_ingestor"):
            return [
                "Sourced research memory ingestion status unavailable."
            ]

        return [
            runtime.research_memory_ingestor.setup_status()
        ]

    def _startup_health_status(self, runtime):
        if runtime is None or not hasattr(runtime, "startup_health"):
            return [
                "Startup health status unavailable."
            ]

        issues = runtime.startup_health.issues()

        if not issues:
            return [
                "Startup health check passing."
            ]

        return [
            "Startup health issues: "
            + " ".join(issues)
        ]

    def _presence_status(self, runtime):
        if runtime is None or not hasattr(runtime, "presence"):
            return [
                "Presence status unavailable."
            ]

        return [
            runtime.presence.status_text()
        ]

    def _planner_status(self, runtime):
        if runtime is None or not hasattr(runtime, "planner"):
            return [
                "LLM action planner status unavailable."
            ]

        return [
            runtime.planner.setup_status()
        ]

    def _confirmation_status(self, runtime):
        if runtime is None or not hasattr(runtime, "confirmation_store"):
            return [
                "Confirmation flow status unavailable."
            ]

        return [
            runtime.confirmation_store.setup_status()
        ]

    def _autonomous_goal_status(self, runtime):
        observers = getattr(runtime, "observers", []) if runtime else []

        for observer in observers:
            if observer.__class__.__name__ == "AutonomyObserver":
                return [
                    observer.setup_status()
                ]

        return [
            "Autonomous goal selection status unavailable."
        ]

    def _learning_status(self, runtime):
        if runtime is None or not hasattr(runtime, "learning_policy"):
            return [
                "Autonomous learning status unavailable."
            ]

        return [
            "Autonomous learning loop online."
        ]

    def _behavior_feedback_status(self, runtime):
        if runtime is None or not hasattr(runtime, "behavior_feedback_policy"):
            return [
                "Behavior feedback learning status unavailable."
            ]

        return [
            runtime.behavior_feedback_policy.setup_status()
        ]

    def _memory_status(self):
        try:
            from agent.memory.store import MemoryStore

            store = MemoryStore()

            with store._connect() as conn:
                conn.execute("SELECT 1").fetchone()

            pending = len(store.pending_tasks())
            geocodes = store.count_geocodes()
            research_memories = store.count_memories(source="research")
            behavior_rules = store.count_memories(kind="behavior_rule")
            reflections = store.count_memories(kind="reflection")
            planner_decisions = store.count_planner_decisions()
            autonomous_goals = store.count_autonomous_goals()

            return [
                "Memory database online.",
                f"Pending tasks: {pending}.",
                f"Geocode cache entries: {geocodes}.",
                f"Sourced research memories: {research_memories}.",
                f"Behavior rules: {behavior_rules}.",
                f"Reflection memories: {reflections}.",
                f"Planner decisions recorded: {planner_decisions}.",
                f"Autonomous goals recorded: {autonomous_goals}."
            ]
        except Exception as exc:
            return [
                f"Memory database unavailable: {exc}."
            ]

    def _importance_status(self, runtime):
        if runtime is None or not hasattr(runtime, "importance_policy"):
            return [
                "Importance policy status unavailable."
            ]

        status = runtime.importance_policy.status()
        provider = status.get("provider")

        if status.get("mode") == "model" and provider:
            return [
                f"Importance policy using model provider: {provider}."
            ]

        return [
            "Importance policy using conservative fallback."
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
            "Google Calendar API": "googleapiclient",
            "Google OAuth": "google_auth_oauthlib",
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
