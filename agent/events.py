from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import uuid4


def utc_now():
    return datetime.utcnow().isoformat(timespec="seconds") + "Z"


@dataclass
class Event:
    source: str
    type: str
    payload: dict[str, Any] = field(default_factory=dict)
    priority: int = 0
    created_at: str = field(default_factory=utc_now)
    id: str = field(default_factory=lambda: str(uuid4()))

    @property
    def message(self):
        return self.payload.get("message", "")

    @property
    def action(self):
        return self.payload.get("action", "none")

    def to_dict(self):
        return {
            "id": self.id,
            "source": self.source,
            "type": self.type,
            "payload": self.payload,
            "priority": self.priority,
            "created_at": self.created_at
        }


@dataclass
class Action:
    type: str
    payload: dict[str, Any] = field(default_factory=dict)
    requires_confirmation: bool = False
    created_at: str = field(default_factory=utc_now)
    id: str = field(default_factory=lambda: str(uuid4()))

    def to_dict(self):
        return {
            "id": self.id,
            "type": self.type,
            "payload": self.payload,
            "requires_confirmation": self.requires_confirmation,
            "created_at": self.created_at
        }
