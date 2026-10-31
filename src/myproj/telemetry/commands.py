from typing import Annotated, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

Identifier = Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")]


class CommandRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    command_id: Identifier
    operation: Literal["open_breaker", "close_breaker"]
    expires_in_seconds: int = Field(default=60, ge=1, le=300)
    expected_state_version: int | None = Field(default=None, ge=0, le=2**53 - 1)


class CommandResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal["1.0"]
    message_type: Literal["command_result"]
    device_id: Identifier
    equipment_id: Identifier
    command_id: Identifier
    status: Literal["accepted", "completed", "rejected", "failed"]
    reason: str = Field(max_length=256, pattern=r"^[a-z0-9_]*$")
    state_version: int = Field(strict=True, ge=0, le=2**53 - 1)
    breaker_state: Literal["open", "closed"]
    event_time: AwareDatetime
