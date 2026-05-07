from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class HandoffRecord:
    id: int
    session_id: str
    timestamp: str
    kind: str
    goal_summary: str
    current_state_summary: str
    unresolved_questions: str
    validation_state: str
    files_touched: str
    suggested_next_actions: str
    final_disposition: str
    human_notes: str
    resume_brief: str
    automation_recommendations_json: str

    @classmethod
    def from_row(cls, row: Any) -> "HandoffRecord":
        return cls(**dict(row))
