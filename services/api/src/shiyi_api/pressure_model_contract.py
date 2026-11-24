"""Research-only retrospective evaluation of personal self-report prediction."""
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field


class PressureResearchConsent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    granted: bool
    policy_version: Literal["pressure-research-v1"]


class PressureEvaluationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source: Literal["gadgetbridge", "health_connect"]
    data_origin: str = Field(min_length=1, max_length=200)
    device_scope: str = Field(pattern=r"^[0-9a-f]{32}$")


class EvaluationMetrics(BaseModel):
    model: Literal["personal_median", "context_ridge", "physiology_context_ridge"]
    mae: float
    rmse: float
    mean_error: float


class PressureEvaluation(BaseModel):
    algorithm: Literal["personal_ridge_v1"] = "personal_ridge_v1"
    status: Literal["insufficient_data", "evaluated_research_only"]
    alignment: Literal["retrospective_event_time"] = "retrospective_event_time"
    as_of: AwareDatetime
    total_checkins: int
    eligible_pairs: int
    independent_pairs: int
    train_count: int
    test_count: int
    train_days: int
    test_days: int
    split_at: AwareDatetime | None = None
    metrics: list[EvaluationMetrics]
    reasons: list[str]
    physiology_improvement_mae: float | None = None
    deployable: Literal[False] = False
