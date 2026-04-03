from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class ValidationHistoryRecord:
    id: int
    session_id: str
    timestamp: str
    kind: str
    activity: str | None
    status: str | None
    source: str
    details_json: str | None

    @classmethod
    def from_row(cls, row: Any) -> "ValidationHistoryRecord":
        return cls(**dict(row))
