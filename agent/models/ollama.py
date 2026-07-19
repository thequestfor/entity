import json
import os
from urllib.error import URLError
from urllib.request import Request, urlopen

from agent.models.base import ModelProvider, ModelUnavailable


class OllamaProvider(ModelProvider):
    name = "ollama"

    def __init__(self):
        self.url = os.getenv(
            "ENTITY_LOCAL_LLM_URL",
            "http://localhost:11434"
        ).rstrip("/")
        self.model = os.getenv("ENTITY_LOCAL_LLM_MODEL")
        self.enabled = (
            os.getenv("ENTITY_LOCAL_LLM_PROVIDER", "").lower()
            == "ollama"
        )

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

    def generate(self, prompt, temperature=0):
        if not self.available():
            raise ModelUnavailable(
                "Ollama is not configured or reachable."
            )

        try:
            with urlopen(
                self._request(prompt, temperature, stream=False),
                timeout=30
            ) as response:
                payload = json.loads(
                    response.read().decode("utf-8")
                )
        except (OSError, URLError, json.JSONDecodeError) as exc:
            raise ModelUnavailable(str(exc)) from exc

        return payload.get("response", "")

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

    def _request(self, prompt, temperature, stream):
        body = json.dumps(
            {
                "model": self.model,
                "prompt": prompt,
                "stream": stream,
                "options": {
                    "temperature": temperature
                }
            }
        ).encode("utf-8")

        return Request(
            f"{self.url}/api/generate",
            data=body,
            headers={
                "Content-Type": "application/json"
            },
            method="POST"
        )
