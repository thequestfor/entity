from agent.models.base import ModelProvider, ModelUnavailable


class LocalStubProvider(ModelProvider):
    name = "local_stub"

    def available(self):
        return False

    def generate(self, prompt, temperature=0):
        raise ModelUnavailable(
            "No local model provider is configured."
        )
