"""Versioned, explainable wearable state. No diagnosis or clinical probability."""
from datetime import date
from typing import Literal

from pydantic import AwareDatetime, BaseModel

from .health_contract import WearableStream

Feature = Literal["recorded_sleep_minutes", "recorded_steps", "resting_hr_bpm", "low_step_hr_bpm"]
Direction = Literal["lower", "higher", "within_reference", "insufficient"]


class DayFeature(BaseModel):
    day: date
    value: float | None
    observations: int
    coverage_minutes: int | None = None
    eligible: bool
    reasons: list[str]


class FeatureState(BaseModel):
    feature: Feature
    baseline_days: int
    baseline_median: float | None
    baseline_mad: float | None
    recent: list[DayFeature]
    deviation_z: float | None
    trend_per_day: float | None
    direction: Direction
    evidence: Literal["insufficient", "limited", "adequate_for_rule"]


class StateEvent(BaseModel):
    code: Literal[
        "recorded_sleep_lower", "recorded_steps_lower", "resting_hr_higher",
        "low_step_hr_higher",
    ]
    feature: Feature
    days: list[date]
    baseline_median: float
    recent_values: list[float]
    evidence: Literal["limited", "adequate_for_rule"]


class HealthStateView(BaseModel):
    algorithm: Literal["robust_baseline_v1"] = "robust_baseline_v1"
    stream: WearableStream
    timezone: str
    as_of: AwareDatetime
    last_observed_at: AwareDatetime | None
    baseline_start: date
    baseline_end: date
    recent_start: date
    recent_end: date
    features: list[FeatureState]
    events: list[StateEvent]
    pressure_status: Literal["insufficient_evidence"] = "insufficient_evidence"
    pressure_reasons: list[str]
