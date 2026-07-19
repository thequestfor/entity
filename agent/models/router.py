import json

from agent.models.base import ModelUnavailable
from agent.models.cloud_openai import CloudOpenAIProvider
from agent.models.local_stub import LocalStubProvider
from agent.models.ollama import OllamaProvider


class ModelRouter:
    def __init__(self, providers=None):
        self.providers = providers or [
            OllamaProvider(),
            CloudOpenAIProvider(),
            LocalStubProvider()
        ]

    def provider(self):
        for provider in self.providers:
            if provider.available():
                return provider

        return None

    def generate(self, prompt, temperature=0):
        provider = self.provider()

        if provider is None:
            raise ModelUnavailable(
                "No configured model provider is available."
            )

        return provider.generate(
            prompt,
            temperature=temperature
        )

    def stream(self, prompt, temperature=0):
        provider = self.provider()

        if provider is None:
            raise ModelUnavailable(
                "No configured model provider is available."
            )

        yield from provider.stream(
            prompt,
            temperature=temperature
        )

    def provider_name(self):
        provider = self.provider()

        if provider is None:
            return None

        return provider.name

    def generate_json(self, prompt, temperature=0):
        text = self.generate(
            prompt,
            temperature=temperature
        )

        return self._parse_json(text)

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
