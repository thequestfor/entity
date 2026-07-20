import json
import re

from agent.models.base import ModelUnavailable
from agent.models.cloud_openai import CloudOpenAIProvider
from agent.models.local_stub import LocalStubProvider
from agent.models.ollama import OllamaProvider


COMPLEXITY_PATTERNS = [
    r"\bcalculate\b",
    r"\bsolve\b",
    r"\bcompare\b",
    r"\bplan\b",
    r"\bcoordinate\b",
    r"\bschedule\b",
    r"\bcalendar\b",
    r"\bevery week\b",
    r"\brecurring\b",
    r"\bwhy\b",
    r"\bhow should\b",
    r"\bwhat should\b",
    r"\bdiagnose\b",
    r"\bdebug\b",
    r"\banalyze\b",
    r"\bthink\b",
    r"\breason\b",
    r"\bif\b.*\bthen\b",
    r"\d+\s*[-+*/]\s*\d+",
    r"\d+\s+(times|multiplied by|divided by|plus|minus)\s+\d+"
]

CALENDAR_PLANNING_PATTERNS = [
    r"\bconflict\b",
    r"\bfree\b",
    r"\bavailable\b",
    r"\bmove\b",
    r"\breschedule\b",
    r"\bbest time\b",
    r"\bfind a time\b",
    r"\btraffic\b",
    r"\bcommute\b",
    r"\bleave\b",
    r"\btravel\b",
    r"\bplan\b",
    r"\bcoordinate\b",
    r"\bif\b.*\bthen\b"
]

REMINDER_PLANNING_PATTERNS = [
    r"\bbefore my next\b",
    r"\bwhen\b",
    r"\bif\b",
    r"\bunless\b",
    r"\bafter\b",
    r"\bbased on\b",
    r"\bcalendar\b",
    r"\bclass\b",
    r"\bwork\b",
    r"\barrive\b",
    r"\bleave\b"
]


class ModelRouter:
    def __init__(self, providers=None):
        if providers is not None:
            self.providers = providers
            return

        reasoning_model = self._reasoning_model()
        local_enabled = (
            OllamaProvider().enabled
        )

        self.providers = [
            OllamaProvider(
                name="local_fast",
                model_env="ENTITY_LOCAL_LLM_MODEL",
                think=False
            ),
            OllamaProvider(
                name="local_thinking",
                model=reasoning_model,
                think=True,
                enabled=local_enabled
            ),
            CloudOpenAIProvider(),
            LocalStubProvider()
        ]

    def provider(self):
        for provider in self.providers:
            if provider.available():
                return provider

        return None

    def generate(
        self,
        prompt,
        temperature=0,
        user_input=None,
        on_escalation=None,
        routing="auto"
    ):
        errors = []

        for provider in self._providers_for(user_input, on_escalation, routing):
            try:
                return provider.generate(
                    prompt,
                    temperature=temperature
                )
            except ModelUnavailable as exc:
                errors.append(f"{provider.name}: {exc}")
                continue
            except Exception as exc:
                errors.append(f"{provider.name}: {exc}")
                continue

        raise ModelUnavailable(
            "No configured model provider is available. "
            + " ".join(errors)
        )

    def stream(
        self,
        prompt,
        temperature=0,
        user_input=None,
        on_escalation=None,
        routing="auto"
    ):
        errors = []

        for provider in self._providers_for(user_input, on_escalation, routing):
            try:
                yield from provider.stream(
                    prompt,
                    temperature=temperature
                )
                return
            except ModelUnavailable as exc:
                errors.append(f"{provider.name}: {exc}")
                continue
            except Exception as exc:
                errors.append(f"{provider.name}: {exc}")
                continue

        raise ModelUnavailable(
            "No configured model provider is available. "
            + " ".join(errors)
        )

    def provider_name(self):
        provider = self.provider()

        if provider is None:
            return None

        return provider.name

    def generate_json(
        self,
        prompt,
        temperature=0,
        user_input=None,
        on_escalation=None,
        routing="auto"
    ):
        text = self.generate(
            prompt,
            temperature=temperature,
            user_input=user_input,
            on_escalation=on_escalation,
            routing=routing
        )

        return self._parse_json(text)

    def should_escalate(self, user_input):
        if not user_input:
            return False

        normalized = user_input.lower()

        return any(
            re.search(pattern, normalized)
            for pattern in COMPLEXITY_PATTERNS
        )

    def _providers_for(self, user_input, on_escalation, routing):
        if routing == "calendar_extract":
            if self._needs_calendar_planning(user_input):
                return self._available_sequence(
                    preferred=["local_thinking", "cloud_openai", "local_fast"],
                    on_escalation=on_escalation,
                    reason=(
                        "This calendar request needs planning, conflict "
                        "checking, travel, or coordination."
                    )
                )

            return self._available_sequence(
                preferred=["local_fast", "local_thinking", "cloud_openai"],
                on_escalation=on_escalation,
                reason="The fast local model is unavailable for calendar extraction."
            )

        if routing == "reminder_extract":
            if self._needs_reminder_planning(user_input):
                return self._available_sequence(
                    preferred=["local_thinking", "cloud_openai", "local_fast"],
                    on_escalation=on_escalation,
                    reason=(
                        "This reminder request depends on context, timing, "
                        "or conditional planning."
                    )
                )

            return self._available_sequence(
                preferred=["local_fast", "local_thinking", "cloud_openai"],
                on_escalation=on_escalation,
                reason="The fast local model is unavailable for reminder extraction."
            )

        if routing == "learning":
            return self._available_sequence(
                preferred=["local_fast", "local_thinking", "cloud_openai"],
                on_escalation=on_escalation,
                reason="The fast local model is unavailable for learning."
            )

        if routing == "research":
            return self._available_sequence(
                preferred=["local_fast", "local_thinking", "cloud_openai"],
                on_escalation=on_escalation,
                reason="The fast local model is unavailable for research summarization."
            )

        if self.should_escalate(user_input):
            return self._available_sequence(
                preferred=["local_thinking", "cloud_openai", "local_fast"],
                on_escalation=on_escalation,
                reason="This request needs calculation, planning, or coordination."
            )

        return self._available_sequence(
            preferred=["local_fast", "local_thinking", "cloud_openai"],
            on_escalation=on_escalation,
            reason="The fast local model is unavailable."
        )

    def _needs_calendar_planning(self, user_input):
        if not user_input:
            return False

        normalized = user_input.lower()

        return any(
            re.search(pattern, normalized)
            for pattern in CALENDAR_PLANNING_PATTERNS
        )

    def _needs_reminder_planning(self, user_input):
        if not user_input:
            return False

        normalized = user_input.lower()

        return any(
            re.search(pattern, normalized)
            for pattern in REMINDER_PLANNING_PATTERNS
        )

    def _available_sequence(self, preferred, on_escalation, reason):
        providers = {
            provider.name: provider
            for provider in self.providers
        }

        for index, name in enumerate(preferred):
            provider = providers.get(name)

            if provider is None or not provider.available():
                continue

            if index > 0 or name in {"local_thinking", "cloud_openai"}:
                self._notify_escalation(provider, on_escalation, reason)

            yield provider

    def _notify_escalation(self, provider, on_escalation, reason):
        if on_escalation is None:
            return

        if provider.name == "local_thinking":
            message = (
                "Escalating to the local thinking model. "
                f"{reason}"
            )
        elif provider.name == "cloud_openai":
            message = (
                "Escalating to cloud AI. "
                f"{reason}"
            )
        else:
            message = (
                f"Using {provider.name}. {reason}"
            )

        on_escalation(message)

    def _reasoning_model(self):
        model = self._env("ENTITY_LOCAL_REASONING_LLM_MODEL")

        if model:
            return model

        return self._env("ENTITY_LOCAL_LLM_MODEL")

    def _env(self, name):
        import os

        return os.getenv(name)

    def _parse_json(self, text):
        text = text.strip()

        if text.startswith("```"):
            lines = text.splitlines()

            if lines and lines[0].startswith("```"):
                lines = lines[1:]

            if lines and lines[-1].startswith("```"):
                lines = lines[:-1]

            text = "\n".join(lines).strip()

        start = text.find("{")
        end = text.rfind("}")

        if start == -1 or end == -1 or end <= start:
            raise ModelUnavailable(
                "Model response did not contain JSON."
            )

        return json.loads(text[start:end + 1])
