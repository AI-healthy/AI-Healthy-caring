"""Typed requests and allowlisted decisions. No free-text or raw health export."""
from datetime import time
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, StrictInt, field_validator

from ..schemas import ActivityOption, SessionResponse

Tag = Literal["gentle", "movement", "outdoor", "music", "culture"]
Trigger = Literal["user_request", "scheduled_check"]
RunStatus = Literal[
    "AWAITING_CONFIRMATION", "NO_ACTION", "CONFIRMED", "DISMISSED", "EXPIRED", "INVALIDATED"
]


class Settings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    use_observations: bool = False
    use_feedback_memory: bool = False
    use_behavior_memory: bool = False
    memory_budget: StrictInt = Field(default=12, ge=1, le=20)
    use_local_model: bool = False
    preference_tags: list[Tag] = Field(default_factory=list, max_length=5)
    blocked_activity_ids: list[str] = Field(default_factory=list, max_length=50)
    proactive_enabled: bool = False
    timezone: str = Field(default="Asia/Shanghai", max_length=64)
    quiet_start: time = time(22, 0)
    quiet_end: time = time(8, 0)

    @field_validator("timezone")
    @classmethod
    def valid_timezone(cls, value):
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError("Unknown IANA time zone") from None
        return value

    @field_validator("quiet_start", "quiet_end")
    @classmethod
    def local_time(cls, value):
        if value.tzinfo is not None:
            raise ValueError("Use local wall-clock times")
        return value


class RunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    client_request_id: str = Field(min_length=1, max_length=80)
    trigger: Trigger = "user_request"
    available_minutes: StrictInt = Field(default=5, ge=1, le=120)
    energy_level: StrictInt | None = Field(default=None, ge=1, le=5)
    availability: Literal["ready", "unwell", "busy"] = "ready"
    skip_activity_ids: list[str] = Field(default_factory=list, max_length=50)


class Trace(BaseModel):
    stage: str
    result: str


class RunView(BaseModel):
    run_id: str
    trigger: Trigger
    status: RunStatus
    algorithm: str
    options: list[ActivityOption]
    trace: list[Trace]
    reason: str
    created_at: AwareDatetime
    expires_at: AwareDatetime
    selected_activity_id: str | None = None
    session_id: str | None = None
    is_demo: Literal[True] = True


class Selection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    activity_id: str = Field(min_length=1, max_length=64)


class ConfirmResult(BaseModel):
    run: RunView
    session: SessionResponse


class MemoryEntry(BaseModel):
    activity_id: str
    count: int
    score: float
    effective_weight: float = 0.0
    recent_completions: int = 0
    repetition_penalty: float = 0.0
    decision_score: float = 0.0


class MemoryView(BaseModel):
    enabled: bool
    behavior_enabled: bool = False
    budget: int = 12
    recalled_events: int = 0
    behavior_events: int = 0
    entries: list[MemoryEntry]
    is_demo: Literal[True] = True
