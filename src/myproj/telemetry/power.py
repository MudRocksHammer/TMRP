import json
import math
from dataclasses import dataclass, fields
from datetime import datetime, timezone
from enum import Enum
from typing import Self

from myproj.telemetry.messageType import MessageType

MEASUREMENT_FIELDS = (
    "voltage_ab_v",
    "voltage_bc_v",
    "voltage_ca_v",
    "current_a_a",
    "current_b_a",
    "current_c_a",
    "active_power_kw",
    "frequency_hz",
)


class PowerTelemetryValidationError(ValueError):
    """電力Telemetryの型・値・品質が契約に違反している。"""


class BreakerState(Enum):
    OPEN = "open"
    CLOSED = "closed"
    UNKNOWN = "unknown"


class MeasurementQuality(Enum):
    GOOD = "good"
    PARTIAL = "partial"
    UNAVAILABLE = "unavailable"


def _require_string(name: str, value: object) -> str:
    if not isinstance(value, str):
        raise PowerTelemetryValidationError(f"{name} must be a string")
    return value


def _normalize_measurement(name: str, value: object) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PowerTelemetryValidationError(f"{name} must be a number or null")
    try:
        number = float(value)
    except OverflowError as exc:
        raise PowerTelemetryValidationError(f"{name} must be finite") from exc
    if not math.isfinite(number):
        raise PowerTelemetryValidationError(f"{name} must be finite")
    # 有効電力は逆方向を負値で表す。実効電圧・実効電流・周波数は非負。
    if name != "active_power_kw" and number < 0:
        raise PowerTelemetryValidationError(f"{name} must be non-negative")
    return number


@dataclass
class PowerTelemetry:
    schema_version: str
    message_type: MessageType
    device_id: str
    boot_id: str
    sequence_no: int
    event_time: datetime
    breaker_state: BreakerState
    quality: MeasurementQuality
    voltage_ab_v: float | None
    voltage_bc_v: float | None
    voltage_ca_v: float | None
    current_a_a: float | None
    current_b_a: float | None
    current_c_a: float | None
    active_power_kw: float | None
    frequency_hz: float | None

    def __post_init__(self) -> None:
        if _require_string("schema_version", self.schema_version) != "1.0":
            raise PowerTelemetryValidationError("schema_version must be '1.0'")
        if self.message_type is not MessageType.POWER:
            raise PowerTelemetryValidationError(
                "message_type must be MessageType.POWER"
            )
        for name in ("device_id", "boot_id"):
            value = _require_string(name, getattr(self, name))
            if not value or value != value.strip():
                raise PowerTelemetryValidationError(
                    f"{name} must be non-empty without surrounding whitespace"
                )
        if (
            isinstance(self.sequence_no, bool)
            or not isinstance(self.sequence_no, int)
            or self.sequence_no < 0
        ):
            raise PowerTelemetryValidationError(
                "sequence_no must be a non-negative integer"
            )
        if not isinstance(self.event_time, datetime):
            raise PowerTelemetryValidationError("event_time must be a datetime")
        try:
            if self.event_time.utcoffset() is None:
                raise ValueError("Timezone is required")
            self.event_time = self.event_time.astimezone(timezone.utc)
        except (ValueError, OverflowError) as exc:
            raise PowerTelemetryValidationError(
                "event_time must have a timezone and be representable in UTC"
            ) from exc
        if not isinstance(self.breaker_state, BreakerState):
            raise PowerTelemetryValidationError("breaker_state must be a BreakerState")
        if not isinstance(self.quality, MeasurementQuality):
            raise PowerTelemetryValidationError("quality must be a MeasurementQuality")

        missing = 0
        for name in MEASUREMENT_FIELDS:
            measurement = _normalize_measurement(name, getattr(self, name))
            setattr(self, name, measurement)
            missing += measurement is None

        if missing == 0:
            expected_quality = MeasurementQuality.GOOD
        elif missing == len(MEASUREMENT_FIELDS):
            expected_quality = MeasurementQuality.UNAVAILABLE
        else:
            expected_quality = MeasurementQuality.PARTIAL
        if self.quality is not expected_quality:
            raise PowerTelemetryValidationError(
                "quality does not match the number of missing measurements"
            )

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "message_type": self.message_type.value,
            "device_id": self.device_id,
            "boot_id": self.boot_id,
            "sequence_no": self.sequence_no,
            "event_time": self.event_time.astimezone(timezone.utc).isoformat(),
            "breaker_state": self.breaker_state.value,
            "quality": self.quality.value,
            **{name: getattr(self, name) for name in MEASUREMENT_FIELDS},
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, allow_nan=False)

    @classmethod
    def from_dict(cls, data: object) -> Self:
        if not isinstance(data, dict):
            raise PowerTelemetryValidationError("Input data must be a dictionary")
        required = {field.name for field in fields(cls)}
        missing = required - data.keys()
        unknown = data.keys() - required
        if missing:
            raise PowerTelemetryValidationError(f"Missing required fields: {missing}")
        if unknown:
            raise PowerTelemetryValidationError(f"Unknown fields: {unknown}")

        schema_version = _require_string("schema_version", data["schema_version"])
        device_id = _require_string("device_id", data["device_id"])
        boot_id = _require_string("boot_id", data["boot_id"])
        sequence_no = data["sequence_no"]
        if isinstance(sequence_no, bool) or not isinstance(sequence_no, int):
            raise PowerTelemetryValidationError("sequence_no must be an integer")
        try:
            event_time = datetime.fromisoformat(
                _require_string("event_time", data["event_time"])
            )
        except ValueError as exc:
            raise PowerTelemetryValidationError(
                "event_time must be an ISO 8601 datetime with timezone"
            ) from exc
        try:
            message_type = MessageType(
                _require_string("message_type", data["message_type"])
            )
        except ValueError as exc:
            raise PowerTelemetryValidationError("Invalid message_type") from exc
        try:
            breaker_state = BreakerState(
                _require_string("breaker_state", data["breaker_state"])
            )
        except ValueError as exc:
            raise PowerTelemetryValidationError("Invalid breaker_state") from exc
        try:
            quality = MeasurementQuality(_require_string("quality", data["quality"]))
        except ValueError as exc:
            raise PowerTelemetryValidationError("Invalid quality") from exc

        return cls(
            schema_version=schema_version,
            message_type=message_type,
            device_id=device_id,
            boot_id=boot_id,
            sequence_no=sequence_no,
            event_time=event_time,
            breaker_state=breaker_state,
            quality=quality,
            voltage_ab_v=_normalize_measurement("voltage_ab_v", data["voltage_ab_v"]),
            voltage_bc_v=_normalize_measurement("voltage_bc_v", data["voltage_bc_v"]),
            voltage_ca_v=_normalize_measurement("voltage_ca_v", data["voltage_ca_v"]),
            current_a_a=_normalize_measurement("current_a_a", data["current_a_a"]),
            current_b_a=_normalize_measurement("current_b_a", data["current_b_a"]),
            current_c_a=_normalize_measurement("current_c_a", data["current_c_a"]),
            active_power_kw=_normalize_measurement(
                "active_power_kw", data["active_power_kw"]
            ),
            frequency_hz=_normalize_measurement("frequency_hz", data["frequency_hz"]),
        )

    @classmethod
    def from_json(cls, text: str) -> Self:
        try:
            data = json.loads(text)
        except (json.JSONDecodeError, TypeError) as exc:
            raise PowerTelemetryValidationError("Invalid JSON") from exc
        return cls.from_dict(data)
