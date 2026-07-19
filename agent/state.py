from typing import TypedDict, Optional


class EntityState(TypedDict):

    mode: str

    activity: Optional[str]

    user_present: bool

    last_input: Optional[str]

    last_response: Optional[str]

    priority: int

    user_input: str

    response: str

    action: str