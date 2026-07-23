from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class SourceItem:
    external_id: str
    title: str
    url: str
    summary: str = ""
    content: str = ""
    published_at: str | None = None
    category: str = "general"
    latitude: float | None = None
    longitude: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    status: str = "active"


@dataclass(frozen=True)
class ConnectorBatch:
    items: list[SourceItem] = field(default_factory=list)
    cursor: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class IngestResult:
    inserted: int = 0
    updated: int = 0
    duplicates: int = 0

    @property
    def changed(self):
        return self.inserted + self.updated
