"""Explicit, time-limited synthetic-data availability and delivery contracts."""
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

from .contracts import RunView

Channel = Literal["app", "simulator"]


class ScheduleRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: StrictBool
    available_minutes: StrictInt = Field(default=5, ge=1, le=30)
    available_for_minutes: StrictInt = Field(default=30, ge=15, le=120)
    channel: Channel = "app"
    device_id: str | None = Field(default=None, min_length=1, max_length=80)

    @model_validator(mode="after")
    def validate_target(self):
        if (self.channel == "simulator") != (self.device_id is not None):
            raise ValueError("Simulator channel requires exactly one device ID")
        return self


class ScheduleView(ScheduleRequest):
    available_until: AwareDatetime | None = None
    next_check_at: AwareDatetime | None = None
    last_reason: str | None = None
    is_demo: Literal[True] = True


class OfferView(BaseModel):
    offer_id: str
    channel: Channel
    device_id: str | None
    acknowledged_at: AwareDatetime | None
    run: RunView
    is_demo: Literal[True] = True


class DeviceOffer(BaseModel):
    offer_id: str
    message_code: Literal["ACTIVITY_INVITATION"] = "ACTIVITY_INVITATION"
    expires_at: AwareDatetime
    is_demo: Literal[True] = True


class DeliveryReceipt(BaseModel):
    offer_id: str
    acknowledged_at: AwareDatetime
    is_demo: Literal[True] = True
