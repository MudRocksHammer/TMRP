from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class MessageType(Enum):
    TELEMETRY = "telemetry"


class TelemetryValidationError(ValueError):
    """テレメトリーデータが仕様を満たさない場合の例外"""


@dataclass
class TelemetryMessage:
    schema_version: str
    device_id: str
    sequence_no: int
    event_time: datetime
    message_type: MessageType
    battery_percent: float | None = None
    temperature_c: float | None = None
    network_rssi: int | None = None
    status_flags: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.schema_version != "1.0":
            raise TelemetryValidationError("schema_version must be '1.0'")
        if self.sequence_no < 0:
            raise TelemetryValidationError("sequence_no must be non-negative")
        if self.battery_percent is not None and not (0 <= self.battery_percent <= 100):
            raise TelemetryValidationError("battery_percent must be between 0 and 100")
        if self.temperature_c is not None and not (
            -273.15 <= self.temperature_c <= 100
        ):
            raise TelemetryValidationError(
                "temperature_c must be between -273.15 and 100"
            )
        if self.network_rssi is not None and not (-100 <= self.network_rssi <= 0):
            raise TelemetryValidationError("network_rssi must be between -100 and 0")
        if self.device_id is None or not self.device_id.strip():
            raise TelemetryValidationError("device_id must be a non-empty string")
        if (
            self.event_time is None
            or not isinstance(self.event_time, datetime)
            or self.event_time.tzinfo is None
            or self.event_time.utcoffset() is None
        ):
            raise TelemetryValidationError("event_time must be a valid datetime object")
        if self.message_type != MessageType.TELEMETRY:
            raise TelemetryValidationError("message_type must be MessageType.TELEMETRY")
        if not isinstance(self.status_flags, list) or not all(
            isinstance(flag, str) for flag in self.status_flags
        ):
            raise TelemetryValidationError("status_flags must be a list of strings")
