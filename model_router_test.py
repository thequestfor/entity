from agent.models.base import ModelProvider
from agent.models.router import ModelRouter


class FakeUnavailableProvider(ModelProvider):
    name = "unavailable"

    def available(self):
        return False

    def generate(self, prompt, temperature=0):
        return "bad"


class FakeStreamingProvider(ModelProvider):
    name = "streaming"

    def available(self):
        return True

    def generate(self, prompt, temperature=0):
        return f"generated: {prompt}"

    def stream(self, prompt, temperature=0):
        yield "streamed "
        yield prompt


router = ModelRouter(
    providers=[
        FakeUnavailableProvider(),
        FakeStreamingProvider()
    ]
)

assert router.provider_name() == "streaming"
assert router.generate("hello") == "generated: hello"
assert "".join(router.stream("hello")) == "streamed hello"

print("model router ok")
