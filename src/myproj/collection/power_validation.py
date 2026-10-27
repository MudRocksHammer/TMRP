import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from myproj.telemetry.power import PowerTelemetry, PowerTelemetryValidationError


class RejectedTelemetry(ValueError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def topic_device_id(topic: str) -> str:
    parts = topic.split("/")
    if (
        len(parts) != 4
        or parts[:2] != ["tmrp", "devices"]
        or parts[-1] != "telemetry"
        or not parts[2]
        or parts[2] != parts[2].strip()
        or len(parts[2]) > 128
        or any(char in topic for char in ("+", "#", "\x00"))
    ):
        raise RejectedTelemetry("invalid_topic")
    return parts[2]


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise RejectedTelemetry("invalid_json")
        result[key] = value
    return result


def _reject_constant(value: str) -> Any:
    raise RejectedTelemetry("invalid_json")


def strict_json(text: str) -> Any:
    depth, in_string, escaped = 0, False, False
    for char in text:
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
        elif char == '"':
            in_string = True
        elif char in "[{":
            depth += 1
            if depth > 32:
                raise RejectedTelemetry("invalid_json")
        elif char in "]}":
            depth -= 1
    try:
        result = json.loads(
            text, object_pairs_hook=_unique_object, parse_constant=_reject_constant
        )
        # エスケープされた単独サロゲートやNULはPostgreSQL JSONBへ渡さない。
        encoded = json.dumps(result, ensure_ascii=False)
        encoded.encode("utf-8")
        if "\\u0000" in encoded:
            # 文字列としての「\\u0000」は許可するため、値を個別に確認する。
            _reject_nul(result)
        return result
    except (ValueError, RecursionError) as exc:
        raise RejectedTelemetry("invalid_json") from exc


def _reject_nul(value: Any) -> None:
    if isinstance(value, str) and "\x00" in value:
        raise RejectedTelemetry("invalid_json")
    if isinstance(value, dict):
        for key, item in value.items():
            _reject_nul(key)
            _reject_nul(item)
    elif isinstance(value, list):
        for item in value:
            _reject_nul(item)


def load_power_devices(path: Path) -> frozenset[str]:
    data = strict_json(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("schema_version") != "1.0":
        raise ValueError("Asset registry must have schema_version 1.0")
    devices = data.get("devices")
    if not isinstance(devices, list) or not devices:
        raise ValueError("Asset registry must contain devices")
    ids: set[str] = set()
    for device in devices:
        if not isinstance(device, dict) or device.get("device_type") != "power_meter":
            raise ValueError("Only power_meter devices are supported")
        device_id = device.get("device_id")
        if not isinstance(device_id, str):
            raise ValueError("device_id must be a string")
        topic_device_id(f"tmrp/devices/{device_id}/telemetry")
        if device_id in ids:
            raise ValueError("Duplicate device_id")
        ids.add(device_id)
    return frozenset(ids)


@dataclass(frozen=True)
class PowerReceipt:
    topic: str
    received_at: datetime
    message: PowerTelemetry


class PowerValidator:
    def __init__(self, device_ids: frozenset[str], max_payload_bytes: int = 16384):
        if (
            not device_ids
            or isinstance(max_payload_bytes, bool)
            or not isinstance(max_payload_bytes, int)
            or max_payload_bytes <= 0
        ):
            raise ValueError("Devices and a positive payload limit are required")
        for device_id in device_ids:
            topic_device_id(f"tmrp/devices/{device_id}/telemetry")
        self.device_ids = device_ids
        self.max_payload_bytes = max_payload_bytes

    def parse(
        self,
        topic: str,
        payload: bytes,
        *,
        received_at: datetime,
        qos: int = 1,
        retain: bool = False,
    ) -> PowerReceipt:
        if received_at.utcoffset() is None:
            raise ValueError("received_at must have a timezone")
        device_id = topic_device_id(topic)
        if device_id not in self.device_ids:
            raise RejectedTelemetry("unknown_device")
        if qos != 1:
            raise RejectedTelemetry("unsupported_qos")
        if retain:
            raise RejectedTelemetry("retained_message")
        if len(payload) > self.max_payload_bytes:
            raise RejectedTelemetry("payload_too_large")
        try:
            text = payload.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise RejectedTelemetry("invalid_utf8") from exc
        data = strict_json(text)
        try:
            message = PowerTelemetry.from_dict(data)
        except PowerTelemetryValidationError as exc:
            raise RejectedTelemetry("invalid_telemetry") from exc
        if message.device_id != device_id:
            raise RejectedTelemetry("device_mismatch")
        # DBの一意インデックスとBIGINTへ収まる受信側メタデータ契約。
        if len(message.boot_id) > 128 or message.sequence_no > 2**63 - 1:
            raise RejectedTelemetry("metadata_out_of_range")
        return PowerReceipt(topic, received_at.astimezone(timezone.utc), message)
