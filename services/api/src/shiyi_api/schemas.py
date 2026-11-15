from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class StateContext(BaseModel):
    """Only minimal explicitly submitted signals. None = missing."""

    energy_level: int | None = Field(default=None, ge=1, le=5)
    available_minutes: int = Field(default=10, ge=1, le=120)
    sleep_minutes: int | None = Field(default=None, ge=0, le=1440)
    steps: int | None = Field(default=None, ge=0)
    source: Literal["self_report", "health_connect", "demo"] = "self_report"
    observed_at: datetime | None = None
    is_demo: bool = False


class RecommendationRequest(BaseModel):
    context: StateContext
    preference_tags: list[str] = Field(default_factory=list, max_length=20)
    skip_activity_ids: list[str] = Field(default_factory=list, max_length=100)


class ActivityOption(BaseModel):
    activity_id: str
    title: str
    duration_minutes: int
    reason: str
    risk_level: Literal["low"] = "low"


class RecommendationResponse(BaseModel):
    request_id: str
    algorithm: Literal["rules_v0"] = "rules_v0"
    options: list[ActivityOption]
    explanation: str
    is_demo: bool
    data_notice: str


class FeedbackRequest(BaseModel):
    activity_id: str = Field(min_length=1, max_length=64)
    completed: bool
    session_id: str | None = Field(default=None, min_length=1, max_length=80)
    enjoyment: int | None = Field(default=None, ge=1, le=5)
    perceived_energy_after: int | None = Field(default=None, ge=1, le=5)
    client_event_id: str = Field(min_length=1, max_length=80)


class FeedbackResponse(BaseModel):
    accepted: bool
    event_id: str
    duplicate: bool = False
    notice: str = "已接收反馈；仅存储于本地开发数据库，不用于医疗判断。"


class SessionCreate(BaseModel):
    activity_id: str = Field(min_length=1, max_length=64)
    client_request_id: str | None = Field(default=None, min_length=1, max_length=80)


class SessionResponse(BaseModel):
    session_id: str
    client_request_id: str | None
    activity_id: str
    title: str
    duration_minutes: int
    status: Literal["CREATED", "RUNNING", "COMPLETED", "CANCELLED", "EXPIRED"]
    created_at: datetime
    started_at: datetime | None
    ended_at: datetime | None
    expires_at: datetime
    is_demo: Literal[True] = True
