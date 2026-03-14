from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class EventRecord:
    id: int
    session_id: str
    timestamp: str
    type: str
    message: str
    metadata_json: str | None

    @classmethod
    def from_row(cls, row: Any) -> "EventRecord":
        return cls(**dict(row))
