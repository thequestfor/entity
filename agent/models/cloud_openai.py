import importlib.util
import os

from agent.models.base import ModelProvider, ModelUnavailable


class CloudOpenAIProvider(ModelProvider):
    name = "cloud_openai"

    def __init__(self):
        self.enabled = (
            os.getenv("ENTITY_CLOUD_LLM_ENABLED", "").lower()
            in {"1", "true", "yes"}
        )
        self.model = os.getenv(
            "ENTITY_CLOUD_LLM_MODEL",
            "gpt-4.1-mini"
        )
        effort = os.getenv(
            "ENTITY_CLOUD_LLM_REASONING_EFFORT", "medium"
        ).strip().lower()
        self.reasoning_effort = (
            effort if effort in {
                "none", "low", "medium", "high", "xhigh", "max"
            } else "medium"
        )

    def available(self):
        return (
            self.enabled
            and bool(os.getenv("OPENAI_API_KEY"))
            and importlib.util.find_spec("openai") is not None
        )

    def generate(self, prompt, temperature=0, response_format=None):
        if not self.available():
            raise ModelUnavailable(
                "Cloud OpenAI provider is disabled or missing a key."
            )

        try:
            request = {
                "model": self.model,
                "messages": [
                    {
                        "role": "user",
                        "content": prompt
                    }
                ]
            }

            if self.model.startswith("gpt-5"):
                request["reasoning_effort"] = self.reasoning_effort
            else:
                request["temperature"] = temperature

            if response_format == "json":
                request["response_format"] = {
                    "type": "json_object"
                }

            response = self._client().chat.completions.create(
                **request
            )
        except Exception as exc:
            raise ModelUnavailable(
                f"Cloud OpenAI request failed: {exc}"
            ) from exc

        return response.choices[0].message.content or ""

    def stream(self, prompt, temperature=0):
        if not self.available():
            raise ModelUnavailable(
                "Cloud OpenAI provider is disabled or missing a key."
            )

        try:
            request = {
                "model": self.model,
                "messages": [
                    {
                        "role": "user",
                        "content": prompt
                    }
                ],
                "stream": True
            }
            if self.model.startswith("gpt-5"):
                request["reasoning_effort"] = self.reasoning_effort
            else:
                request["temperature"] = temperature
            response = self._client().chat.completions.create(**request)

            for chunk in response:
                token = chunk.choices[0].delta.content or ""

                if token:
                    yield token
        except Exception as exc:
            raise ModelUnavailable(
                f"Cloud OpenAI request failed: {exc}"
            ) from exc

    def _client(self):
        from openai import OpenAI

        return OpenAI()
