"""ShiYi simulator protocol; this is not the M5Stack native wire format."""
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

Preset = Literal["happy", "neutral", "sleepy"]
CommandStatus = Literal[
    "QUEUED", "ACKNOWLEDGED", "COMPLETED", "FAILED", "EXPIRED", "CANCELLED"
]


class CommandRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: str = Field(min_length=1, max_length=80)
    device_id: str = Field(min_length=1, max_length=80)
    preset: Preset = "happy"
    client_request_id: str = Field(min_length=1, max_length=80)


class ExpressionPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    preset: Preset


class DeviceCommand(BaseModel):
    schema_version: Literal["0.1-draft"] = "0.1-draft"
    command_id: str
    correlation_id: str
    device_id: str
    type: Literal["SET_EXPRESSION"] = "SET_EXPRESSION"
    payload: ExpressionPayload
    expires_at: AwareDatetime
    is_demo: Literal[True] = True


class CommandView(DeviceCommand):
    status: CommandStatus
    created_at: AwareDatetime


class DeviceEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["0.1-draft"]
    event_id: str = Field(min_length=1, max_length=100)
    device_id: str = Field(min_length=1, max_length=80)
    type: Literal["COMMAND_ACKNOWLEDGED", "COMMAND_COMPLETED", "COMMAND_FAILED"]
    command_id: str = Field(min_length=1, max_length=80)
    occurred_at: AwareDatetime
    is_demo: Literal[True]


class Receipt(BaseModel):
    accepted: Literal[True] = True
    duplicate: bool
    command: CommandView
