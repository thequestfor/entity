import dotenv

from agent.models.base import ModelUnavailable
from agent.models.router import ModelRouter


dotenv.load_dotenv()

router = ModelRouter()


def think(prompt, user_input=None, on_escalation=None):
    return router.generate(
        prompt,
        user_input=user_input,
        on_escalation=on_escalation
    )


def stream(prompt, user_input=None, on_escalation=None):
    try:
        yield from router.stream(
            prompt,
            user_input=user_input,
            on_escalation=on_escalation
        )
    except ModelUnavailable as exc:
        yield (
            "I do not have an available language model. "
            f"{exc}"
        )


def active_provider():
    return router.provider_name()
