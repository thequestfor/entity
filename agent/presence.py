from dataclasses import asdict, dataclass

from agent.events import utc_now
from agent.memory.store import MemoryStore


@dataclass
class PresenceSnapshot:
    location: str = "unknown"
    availability: str = "unknown"
    last_seen_at: str = ""
    last_interaction_channel: str = ""
    updated_at: str = ""

    def to_dict(self):
        return asdict(self)


class PresenceState:
    key = "presence"
    valid_locations = {"home", "away", "unknown"}
    valid_availability = {
        "available",
        "busy",
        "sleeping",
        "do_not_disturb",
        "unknown"
    }

    def __init__(self, store=None):
        self.store = store or MemoryStore()

    def snapshot(self):
        data = self.store.get_state(self.key, default={}) or {}

        return PresenceSnapshot(
            location=data.get("location", "unknown"),
            availability=data.get("availability", "unknown"),
            last_seen_at=data.get("last_seen_at", ""),
            last_interaction_channel=data.get(
                "last_interaction_channel",
                ""
            ),
            updated_at=data.get("updated_at", "")
        )

    def update(
        self,
        location=None,
        availability=None,
        interaction_channel=None,
        seen=False
    ):
        current = self.snapshot().to_dict()
        now = utc_now()

        if location:
            current["location"] = self._validated(
                location,
                self.valid_locations,
                "unknown"
            )

        if availability:
            current["availability"] = self._validated(
                availability,
                self.valid_availability,
                "unknown"
            )

        if interaction_channel:
            current["last_interaction_channel"] = interaction_channel

        if seen:
            current["last_seen_at"] = now

        current["updated_at"] = now
        self.store.set_state(self.key, current)

        return PresenceSnapshot(**current)

    def should_speak(self):
        snapshot = self.snapshot()

        if snapshot.availability in {"sleeping", "do_not_disturb"}:
            return False

        if snapshot.location == "away":
            return False

        return True

    def should_notify(self):
        snapshot = self.snapshot()

        return (
            snapshot.location == "away"
            or snapshot.availability in {"sleeping", "do_not_disturb", "busy"}
        )

    def status_text(self):
        snapshot = self.snapshot()

        return (
            f"Presence: {snapshot.location}, {snapshot.availability}. "
            f"Last interaction: "
            f"{snapshot.last_interaction_channel or 'none'}."
        )

    def _validated(self, value, valid, fallback):
        value = value.lower().strip().replace(" ", "_")

        if value in valid:
            return value

        return fallback
