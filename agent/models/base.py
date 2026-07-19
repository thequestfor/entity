from abc import ABC, abstractmethod


class ModelUnavailable(Exception):
    pass


class ModelProvider(ABC):
    name = "base"

    @abstractmethod
    def available(self):
        raise NotImplementedError

    @abstractmethod
    def generate(self, prompt, temperature=0):
        raise NotImplementedError

    def stream(self, prompt, temperature=0):
        yield self.generate(
            prompt,
            temperature=temperature
        )
