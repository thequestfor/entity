import json
import os
from urllib.error import URLError
from urllib.request import Request, urlopen

from agent.models.base import ModelProvider, ModelUnavailable


class OllamaProvider(ModelProvider):
    name = "ollama"

    def __init__(
        self,
        name="ollama",
        model=None,
        model_env="ENTITY_LOCAL_LLM_MODEL",
        think=None,
        enabled=None
    ):
        self.name = name
        self.url = os.getenv(
            "ENTITY_LOCAL_LLM_URL",
            "http://localhost:11434"
        ).rstrip("/")
        self.model = model or os.getenv(model_env)
        self.enabled = self._provider_enabled(enabled)
        self.think = self._configured_think(think)

    def available(self):
        if not self.enabled or not self.model:
            return False

        try:
            with urlopen(
                f"{self.url}/api/tags",
                timeout=0.5
            ) as response:
                return response.status == 200
        except (OSError, URLError):
            return False

    def generate(self, prompt, temperature=0, response_format=None):
        if not self.available():
            raise ModelUnavailable(
                "Ollama is not configured or reachable."
            )

        try:
            with urlopen(
                self._request(
                    prompt,
                    temperature,
                    stream=False,
                    response_format=response_format
                ),
                timeout=30
            ) as response:
                payload = json.loads(
                    response.read().decode("utf-8")
                )
        except (OSError, URLError, json.JSONDecodeError) as exc:
            raise ModelUnavailable(str(exc)) from exc

        response = payload.get("response", "")
        if response or response_format != "json":
            return response

        # Some Ollama reasoning models place a structured answer in the
        # `thinking` field when JSON mode is enabled. It is still the model's
        # final structured output, so expose it to the JSON parser without
        # leaking hidden reasoning into ordinary conversational responses.
        return payload.get("thinking", "")

    def stream(self, prompt, temperature=0):
        if not self.available():
            raise ModelUnavailable(
                "Ollama is not configured or reachable."
            )

        try:
            with urlopen(
                self._request(prompt, temperature, stream=True),
                timeout=60
            ) as response:
                for line in response:
                    if not line.strip():
                        continue

                    payload = json.loads(
                        line.decode("utf-8")
                    )
                    token = payload.get("response", "")

                    if token:
                        yield token

                    if payload.get("done"):
                        break
        except (OSError, URLError, json.JSONDecodeError) as exc:
            raise ModelUnavailable(str(exc)) from exc

    def _request(
        self,
        prompt,
        temperature,
        stream,
        response_format=None
    ):
        payload = {
            "model": self.model,
            "prompt": prompt,
            "stream": stream,
            "think": self.think,
            "options": {
                "temperature": temperature
            }
        }

        if response_format == "json":
            payload["format"] = "json"

        body = json.dumps(payload).encode("utf-8")

        return Request(
            f"{self.url}/api/generate",
            data=body,
            headers={
                "Content-Type": "application/json"
            },
            method="POST"
        )

    def _env_bool(self, name, default=False):
        value = os.getenv(name)

        if value is None or value.strip() == "":
            return default

        return value.lower().strip() in {
            "1",
            "true",
            "yes",
            "on"
        }

    def _provider_enabled(self, enabled):
        if enabled is not None:
            return enabled

        return (
            os.getenv("ENTITY_LOCAL_LLM_PROVIDER", "").lower()
            == "ollama"
        )

    def _configured_think(self, think):
        if think is not None:
            return think

        return self._env_bool(
            "ENTITY_LOCAL_LLM_THINK",
            default=False
        )
