"""ShiYi simulator protocol; this is not the M5Stack native wire format.

LAN-02 whitelist: the device only accepts the six command types below. Every
payload is validated server-side before it can be queued, and the device repeats
the same validation before acting (defense in depth). No free-form servo angles
or arbitrary shell/text commands are accepted.
"""
from typing import Any, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

Preset = Literal["happy", "neutral", "sleepy"]
HeadPreset = Literal["nod", "shake", "tilt", "look_around", "greet"]
CommandType = Literal[
    "SET_EXPRESSION",
    "SET_FACE",
    "SPEAK_TEXT",
    "PLAY_GUIDE",
    "SHOW_TIMER",
    "MOVE_HEAD_PRESET",
    "CANCEL_TASK",
]
CommandStatus = Literal[
    "QUEUED", "ACKNOWLEDGED", "COMPLETED", "FAILED", "EXPIRED", "CANCELLED"
]


class CommandRequest(BaseModel):
    """Client request.

    ``preset`` is the pre-LAN-02 field and stays supported for existing callers.
    New callers send ``command_type`` plus ``payload``.
    """

    model_config = ConfigDict(extra="forbid")

    session_id: str = Field(min_length=1, max_length=80)
    device_id: str = Field(min_length=1, max_length=80)
    client_request_id: str = Field(min_length=1, max_length=80)
    command_type: CommandType = "SET_EXPRESSION"
    preset: Preset | None = None
    payload: dict[str, Any] | None = None


class ExpressionPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    preset: Preset


class SetFacePayload(BaseModel):
    """Extensible face command: base expression plus optional decorator overlay.

    Decorator names come from the community firmware (heart/shy/sweat/dizzy/...).
    Unknown values are rejected by the device at MCP-call time, not here, so new
    overlays can be added without a backend release.
    """

    model_config = ConfigDict(extra="forbid")

    expression: str = Field(default="neutral", min_length=1, max_length=40)
    overlay: str | None = Field(default=None, max_length=40)
    duration_ms: int = Field(default=0, ge=0, le=60000)


class SpeakTextPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1, max_length=200)
    emotion: Preset = "neutral"


class PlayGuidePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    guide_id: str = Field(min_length=1, max_length=40)
    title: str = Field(min_length=1, max_length=80)
    duration_seconds: int = Field(ge=30, le=900)
    steps: list[str] = Field(default_factory=list, max_length=12)


class ShowTimerPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    duration_seconds: int = Field(ge=10, le=3600)
    label: str = Field(min_length=1, max_length=80)


class MoveHeadPresetPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    preset: HeadPreset


class CancelTaskPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: Literal["user_cancel", "session_cancelled", "timeout"] = "user_cancel"


PAYLOAD_MODELS: dict[str, type[BaseModel]] = {
    "SET_EXPRESSION": ExpressionPayload,
    "SET_FACE": SetFacePayload,
    "SPEAK_TEXT": SpeakTextPayload,
    "PLAY_GUIDE": PlayGuidePayload,
    "SHOW_TIMER": ShowTimerPayload,
    "MOVE_HEAD_PRESET": MoveHeadPresetPayload,
    "CANCEL_TASK": CancelTaskPayload,
}


def build_command(request: CommandRequest) -> tuple[CommandType, dict[str, Any]]:
    """Normalize a request to (command type, validated payload).

    Raises ValueError for invalid payloads or mixed legacy/new fields; the API
    turns that into HTTP 422 without echoing user-controlled values.
    """
    if request.command_type == "SET_EXPRESSION":
        if request.payload is not None:
            if request.preset is not None:
                raise ValueError("Use preset or payload, not both")
            model = ExpressionPayload.model_validate(request.payload)
        else:
            model = ExpressionPayload(preset=request.preset or "happy")
        return "SET_EXPRESSION", model.model_dump(mode="json")

    if request.preset is not None:
        raise ValueError("preset is only valid for SET_EXPRESSION")
    if request.payload is None:
        raise ValueError("payload is required for this command type")
    model = PAYLOAD_MODELS[request.command_type].model_validate(request.payload)
    return request.command_type, model.model_dump(mode="json")


class DeviceCommand(BaseModel):
    schema_version: Literal["0.1-draft"] = "0.1-draft"
    command_id: str
    correlation_id: str
    device_id: str
    type: CommandType
    payload: dict[str, Any]
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
    reason: str | None = Field(default=None, max_length=120)
    elapsed_seconds: int | None = Field(default=None, ge=0, le=7200)


class Receipt(BaseModel):
    accepted: Literal[True] = True
    duplicate: bool
    command: CommandView
