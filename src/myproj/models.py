import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Self


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

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "device_id": self.device_id,
            "sequence_no": self.sequence_no,
            "event_time": self.event_time.astimezone(timezone.utc).isoformat(),
            "message_type": self.message_type.value,
            "battery_percent": self.battery_percent,
            "temperature_c": self.temperature_c,
            "network_rssi": self.network_rssi,
            "status_flags": self.status_flags.copy(),
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False)

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> Self:
        if not isinstance(data, dict):
            raise TelemetryValidationError("Input data must be a dictionary")
        required_fields = {
            "schema_version",
            "device_id",
            "sequence_no",
            "event_time",
            "message_type",
        }
        optional_fields = {
            "battery_percent",
            "temperature_c",
            "network_rssi",
            "status_flags",
        }

        missing = required_fields - data.keys()
        unknown = data.keys() - (required_fields | optional_fields)

        if missing:
            raise TelemetryValidationError(f"Missing required fields: {missing}")
        if unknown:
            raise TelemetryValidationError(f"Unknown fields: {unknown}")

        if "schema_version" not in data or data["schema_version"] != "1.0":
            raise TelemetryValidationError("schema_version must be '1.0'")
        if (
            "device_id" not in data
            or not isinstance(data["device_id"], str)
            or not data["device_id"].strip()
        ):
            raise TelemetryValidationError("device_id must be a non-empty string")
        sequence_no = data["sequence_no"]
        if not isinstance(sequence_no, int) or isinstance(sequence_no, bool):
            raise TelemetryValidationError("sequence_no must be a non-negative integer")
        raw_event_time = data["event_time"]
        if not isinstance(raw_event_time, str):
            raise TelemetryValidationError("event_time must be a string")
        try:
            event_time = datetime.fromisoformat(raw_event_time)
        except ValueError as exc:
            raise TelemetryValidationError(
                "event_time must be an ISO 8601 datetime"
            ) from exc
        if (
            "message_type" not in data
            or data["message_type"] != MessageType.TELEMETRY.value
        ):
            raise TelemetryValidationError("message_type must be MessageType.TELEMETRY")
        if "battery_percent" in data and data["battery_percent"] is not None:
            if (
                not isinstance(data["battery_percent"], (int, float))
                or not (0 <= data["battery_percent"] <= 100)
                or isinstance(data["battery_percent"], bool)
            ):
                raise TelemetryValidationError(
                    "battery_percent must be between 0 and 100"
                )
        if "temperature_c" in data and data["temperature_c"] is not None:
            if (
                not isinstance(data["temperature_c"], (int, float))
                or not (-273.15 <= data["temperature_c"] <= 100)
                or isinstance(data["temperature_c"], bool)
            ):
                raise TelemetryValidationError(
                    "temperature_c must be between -273.15 and 100"
                )
        if "network_rssi" in data and data["network_rssi"] is not None:
            if (
                not isinstance(data["network_rssi"], int)
                or not (-100 <= data["network_rssi"] <= 0)
                or isinstance(data["network_rssi"], bool)
            ):
                raise TelemetryValidationError(
                    "network_rssi must be between -100 and 0"
                )
        if "status_flags" in data and not isinstance(data["status_flags"], list):
            raise TelemetryValidationError("status_flags must be a list of strings")
        flags = data.get("status_flags", [])
        if not isinstance(flags, list):
            raise TelemetryValidationError("status_flags must be a list of strings")
        if not all(isinstance(flag, str) for flag in flags):
            raise TelemetryValidationError("All items in status_flags must be strings")

        return cls(
            schema_version=data["schema_version"],
            device_id=data["device_id"],
            sequence_no=sequence_no,
            event_time=event_time,
            message_type=MessageType(data["message_type"]),
            battery_percent=data.get("battery_percent"),
            temperature_c=data.get("temperature_c"),
            network_rssi=data.get("network_rssi"),
            status_flags=flags.copy(),
        )

    @classmethod
    def from_json(cls, text: str) -> Self:
        try:
            data = json.loads(text)
        except json.JSONDecodeError as e:
            raise TelemetryValidationError("Invalid JSON") from e

        return cls.from_dict(data)
