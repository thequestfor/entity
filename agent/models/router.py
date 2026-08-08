import json
import os
import re
import threading
import time
import urllib.error
import urllib.request

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
    r"\bhow should\b",
    r"\bwhat should\b",
    r"\bdiagnose\b",
    r"\bdebug\b",
    r"\banalyze\b",
    r"\bthink (?:deeply|carefully|step by step|through)\b",
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

DEBATE_PATTERNS = [
    r"\bdebate\b",
    r"\bargue\b",
    r"\bdisagree\b",
    r"\byour (?:view|opinion|worldview|assessment)\b",
    r"\bwhy do you (?:think|believe)\b",
    r"\bstrongest (?:case|argument|counterargument)\b",
    r"\bweigh (?:the )?evidence\b",
    r"\bdefend (?:that|your)\b"
]


class ModelRouter:
    def __init__(self, providers=None, unreal_probe=None):
        self._unreal_probe = unreal_probe
        self.last_provider_name = None
        self._provider_failures = {}
        self._provider_retry_at = {}
        self._health_lock = threading.Lock()

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
            if not self._circuit_open(provider.name) and provider.available():
                return provider

        return None

    def generate(
        self,
        prompt,
        temperature=0,
        user_input=None,
        on_escalation=None,
        routing="auto",
        response_format=None
    ):
        errors = []

        for provider in self._providers_for(user_input, on_escalation, routing):
            try:
                response = provider.generate(
                    prompt,
                    temperature=temperature,
                    response_format=response_format
                )
                self.last_provider_name = provider.name
                self._record_provider_success(provider.name)
                return response
            except ModelUnavailable as exc:
                self._record_provider_failure(provider.name, exc)
                errors.append(f"{provider.name}: {exc}")
                continue
            except Exception as exc:
                self._record_provider_failure(provider.name, exc)
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
            yielded = False

            try:
                for token in provider.stream(
                    prompt,
                    temperature=temperature
                ):
                    yielded = True
                    self.last_provider_name = provider.name
                    yield token

                self._record_provider_success(provider.name)
                return
            except ModelUnavailable as exc:
                self._record_provider_failure(provider.name, exc)
                if yielded:
                    raise ModelUnavailable(
                        f"{provider.name} failed after streaming began: {exc}"
                    ) from exc

                errors.append(f"{provider.name}: {exc}")
                continue
            except Exception as exc:
                self._record_provider_failure(provider.name, exc)
                if yielded:
                    raise ModelUnavailable(
                        f"{provider.name} failed after streaming began: {exc}"
                    ) from exc

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
            routing=routing,
            response_format="json"
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

        if routing == "world_understanding":
            preferred = ["local_thinking", "cloud_openai", "local_fast"]
            if self._env_bool("ENTITY_WORLD_UNDERSTANDING_CLOUD_FIRST"):
                preferred = ["cloud_openai", "local_thinking", "local_fast"]
            return self._available_sequence(
                preferred=preferred,
                on_escalation=on_escalation,
                reason=(
                    "Cross-source worldview synthesis requires the reasoning "
                    "model."
                )
            )

        if (
            self._env_bool("ENTITY_DEBATE_CLOUD_FIRST")
            and self._is_debate_request(user_input)
        ):
            return self._available_sequence(
                preferred=["cloud_openai", "local_thinking", "local_fast"],
                on_escalation=on_escalation,
                reason=(
                    "Evidence-heavy opinion and debate use the cloud reasoning "
                    "model when configured."
                )
            )

        if routing == "research":
            return self._available_sequence(
                preferred=["local_fast", "local_thinking", "cloud_openai"],
                on_escalation=on_escalation,
                reason="The fast local model is unavailable for research summarization."
            )

        if routing == "planner":
            if self.should_escalate(user_input):
                return self._available_sequence(
                    preferred=["local_thinking", "cloud_openai", "local_fast"],
                    on_escalation=on_escalation,
                    reason=(
                        "This request needs planning, calculation, scheduling, "
                        "or coordination."
                    )
                )

            return self._available_sequence(
                preferred=["local_fast", "local_thinking", "cloud_openai"],
                on_escalation=on_escalation,
                reason="The fast local model is unavailable for action planning."
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

    def _is_debate_request(self, user_input):
        if not user_input:
            return False
        normalized = user_input.lower()
        return any(re.search(pattern, normalized) for pattern in DEBATE_PATTERNS)

    def _available_sequence(self, preferred, on_escalation, reason):
        cloud_preferred = self._cloud_preferred_for_unreal()

        if cloud_preferred:
            preferred = [
                "cloud_openai",
                *[name for name in preferred if name != "cloud_openai"]
            ]

        providers = {
            provider.name: provider
            for provider in self.providers
        }

        for index, name in enumerate(preferred):
            provider = providers.get(name)

            if (
                provider is None
                or self._circuit_open(name)
                or not provider.available()
            ):
                continue

            if (
                index > 0
                or name == "local_thinking"
                or (name == "cloud_openai" and not cloud_preferred)
            ):
                self._notify_escalation(provider, on_escalation, reason)

            yield provider

    def _circuit_open(self, provider_name):
        with self._health_lock:
            retry_at = self._provider_retry_at.get(provider_name, 0.0)
        return time.monotonic() < retry_at

    def _record_provider_success(self, provider_name):
        with self._health_lock:
            self._provider_failures.pop(provider_name, None)
            self._provider_retry_at.pop(provider_name, None)

    def _record_provider_failure(self, provider_name, error):
        message = str(error).lower()
        quota_failure = any(marker in message for marker in (
            "insufficient_quota",
            "credit_balance_exhausted",
            "no credits remaining"
        ))
        threshold = self._env_int(
            "ENTITY_MODEL_CIRCUIT_FAILURE_THRESHOLD", 3, minimum=1
        )
        with self._health_lock:
            failures = self._provider_failures.get(provider_name, 0) + 1
            self._provider_failures[provider_name] = failures
            if failures < threshold and not quota_failure:
                return
            cooldown = self._env_int(
                "ENTITY_MODEL_QUOTA_COOLDOWN_SECONDS" if quota_failure else
                "ENTITY_MODEL_CIRCUIT_COOLDOWN_SECONDS",
                3600 if quota_failure else 300,
                minimum=30
            )
            self._provider_retry_at[provider_name] = time.monotonic() + cooldown

    def _env_int(self, name, default, minimum=0):
        try:
            value = int(os.getenv(name, str(default)))
        except ValueError:
            value = default
        return max(minimum, value)

    def _cloud_preferred_for_unreal(self):
        if not self._env_bool("ENTITY_PREFER_CLOUD_WHEN_UNREAL"):
            return False

        if not self._env_bool("ENTITY_UNREAL_ENABLED"):
            return False

        if self._unreal_probe is not None:
            return bool(self._unreal_probe())

        base_url = os.getenv(
            "ENTITY_UNREAL_REMOTE_URL",
            "http://127.0.0.1:30010"
        ).rstrip("/")

        try:
            with urllib.request.urlopen(
                f"{base_url}/remote/info",
                timeout=0.25
            ) as response:
                return response.status == 200
        except (OSError, urllib.error.URLError):
            return False

    def _env_bool(self, name):
        return os.getenv(name, "").strip().lower() in {
            "1", "true", "yes", "on"
        }

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
