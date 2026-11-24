"""Typed observation contracts for Android integration."""
from datetime import UTC, date, timedelta
from typing import Literal

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    model_validator,
)

Source = Literal["demo", "self_report", "health_connect", "vendor_sdk", "gadgetbridge"]
Metric = Literal["sleep_minutes", "steps", "energy_level", "resting_heart_rate_bpm", "heart_rate_bpm"]
REAL_METRICS = frozenset({"sleep_minutes", "steps", "heart_rate_bpm", "resting_heart_rate_bpm"})
REAL_POLICY = "local-wearable-v1"
REAL_SOURCES = frozenset({"health_connect", "gadgetbridge"})
RANGES = {
    "sleep_minutes": (0, 1440),
    "steps": (0, 200000),
    "energy_level": (1, 5),
    "resting_heart_rate_bpm": (1, 300),
    "heart_rate_bpm": (1, 300),
}


class ConsentUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    granted: bool
    policy_version: Literal["local-demo-v1", "local-wearable-v1"]


class ConsentView(ConsentUpdate):
    source: Source
    metric: Metric
    updated_at: AwareDatetime


class ObservationInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    client_sample_id: str = Field(min_length=1, max_length=100)
    source: Source
    metric: Metric
    value: StrictInt | None = None
    observed_at: AwareDatetime
    interval_start: AwareDatetime | None = None
    missing_reason: Literal["not_available", "not_worn", "sensor_error", "not_reported"] | None = None
    is_demo: StrictBool
    data_origin: str | None = Field(default=None, min_length=1, max_length=200)
    device_scope: str | None = Field(default=None, pattern=r"^[0-9a-f]{32}$")

    @model_validator(mode="after")
    def check_sample(self):
        if not self.is_demo:
            if self.source not in REAL_SOURCES or self.metric not in REAL_METRICS:
                raise ValueError("Unsupported real observation source or metric")
            if not self.data_origin or not self.data_origin.strip():
                raise ValueError("Real observations require their originating app package")
        elif self.data_origin is not None or self.device_scope is not None:
            raise ValueError("Demo records must not claim a real origin")
        self.observed_at = self.observed_at.astimezone(UTC)
        if self.interval_start is not None:
            self.interval_start = self.interval_start.astimezone(UTC)
        if (self.value is None) != (self.missing_reason is not None):
            raise ValueError("Missing samples must have a reason and no value")
        if self.value is not None:
            low, high = RANGES[self.metric]
            if not low <= self.value <= high:
                raise ValueError("Metric value outside supported input bounds")
        if self.metric == "energy_level" and self.source not in {"self_report", "demo"}:
            raise ValueError("Energy must be self-reported, not inferred from sensors")
        if self.metric in {"steps", "sleep_minutes"}:
            if self.interval_start is None:
                raise ValueError("Interval metric requires interval_start")
            duration = self.observed_at - self.interval_start
            if duration <= timedelta(0) or duration > timedelta(days=1):
                raise ValueError("Interval must be positive and at most 24 hours")
            if (
                self.metric == "sleep_minutes" and self.value is not None
                and timedelta(minutes=self.value) > duration
            ):
                raise ValueError("Sleep duration exceeds observation interval")
        elif self.interval_start is not None:
            raise ValueError("Point metric does not accept interval_start")
        return self


class ObservationBatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    observations: list[ObservationInput] = Field(min_length=1, max_length=100)


class ObservationView(ObservationInput):
    observation_id: str
    recorded_at: AwareDatetime


class ObservationReceipt(BaseModel):
    observation_id: str
    client_sample_id: str
    duplicate: bool


class BatchReceipt(BaseModel):
    items: list[ObservationReceipt]


class ObservationPage(BaseModel):
    items: list[ObservationView]
    next_offset: int | None


class WearableStream(BaseModel):
    source: Literal["gadgetbridge", "health_connect"]
    data_origin: str
    device_scope: str
    metrics: list[Metric]


class WearableSummary(BaseModel):
    stream: WearableStream
    date: date
    timezone: str
    as_of: AwareDatetime
    steps: int | None
    sleep_minutes: int | None
    heart_rate_bpm: int | None
    heart_rate_at: AwareDatetime | None
    resting_heart_rate_bpm: int | None
    resting_heart_rate_at: AwareDatetime | None
    sample_counts: dict[str, int]
    issues: list[str]
