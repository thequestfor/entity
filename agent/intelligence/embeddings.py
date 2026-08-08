import json
import math
import os
from urllib.request import Request, urlopen


class OllamaEmbeddingProvider:
    """Optional local embeddings; never sends intelligence evidence to cloud."""

    def __init__(self, enabled=False, model="", url="", timeout=15):
        self.enabled = bool(enabled)
        self.model = str(model or "").strip()
        self.url = str(
            url or os.getenv("ENTITY_LOCAL_LLM_URL", "http://localhost:11434")
        ).rstrip("/")
        self.timeout = max(1, int(timeout))

    @property
    def name(self):
        return f"ollama:{self.model}"

    def available(self):
        return self.enabled and bool(self.model)

    def embed(self, text):
        if not self.available():
            return None
        request = Request(
            f"{self.url}/api/embed",
            data=json.dumps({
                "model": self.model,
                "input": str(text or "")[:8000]
            }).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        try:
            with urlopen(request, timeout=self.timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except Exception as exc:
            print("Local clustering embeddings unavailable:", exc)
            return None
        embeddings = payload.get("embeddings") or []
        if not embeddings or not isinstance(embeddings[0], list):
            return None
        try:
            return tuple(float(value) for value in embeddings[0])
        except (TypeError, ValueError):
            return None


def cosine_similarity(left, right):
    if not left or not right or len(left) != len(right):
        return 0.0
    dot = sum(a * b for a, b in zip(left, right))
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if not left_norm or not right_norm:
        return 0.0
    return max(-1.0, min(1.0, dot / (left_norm * right_norm)))
