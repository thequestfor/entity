import dotenv

from agent.models.base import ModelUnavailable
from agent.models.router import ModelRouter


dotenv.load_dotenv()

router = ModelRouter()


def think(prompt):
    return router.generate(prompt)


def stream(prompt):
    try:
        yield from router.stream(prompt)
    except ModelUnavailable as exc:
        yield (
            "I do not have an available language model. "
            f"{exc}"
        )


def active_provider():
    return router.provider_name()
