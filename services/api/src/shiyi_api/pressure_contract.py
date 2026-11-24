"""Explicit subjective labels and paired wearable features; never a diagnosis."""
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, StrictInt


class PressureConsent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    granted: bool
    policy_version: Literal["pressure-checkin-v1"]


class PressureCheckinInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    client_checkin_id: str = Field(min_length=1, max_length=80)
    source: Literal["gadgetbridge", "health_connect"]
    data_origin: str = Field(min_length=1, max_length=200)
    device_scope: str = Field(pattern=r"^[0-9a-f]{32}$")
    perceived_stress: StrictInt = Field(ge=0, le=10)
    context: Literal["resting", "studying", "working", "exercise", "other", "unknown"]
    observed_at: AwareDatetime


class PressureCheckin(PressureCheckinInput):
    checkin_id: str
    recorded_at: AwareDatetime


class PressurePair(BaseModel):
    checkin: PressureCheckin
    window_start: AwareDatetime
    window_end: AwareDatetime
    heart_rate_median: float | None
    heart_rate_samples: int
    low_step_hr_median: float | None
    low_step_hr_samples: int
    recorded_steps: int | None
    step_coverage_minutes: int
    eligible_for_research: bool
    reasons: list[str]
    alignment: Literal["retrospective_event_time"] = "retrospective_event_time"
    algorithm: Literal["pressure_pair_v1"] = "pressure_pair_v1"
