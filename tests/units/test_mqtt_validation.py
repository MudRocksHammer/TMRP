import json

import pytest

from myproj.models import TelemetryMessage, TelemetryValidationError
from myproj.mqtt_validation import parse_mqtt_telemetry


@pytest.fixture
def valid_payload() -> bytes:
    return json.dumps(
        {
            "schema_version": "1.0",
            "device_id": "robot-001",
            "sequence_no": 1,
            "event_time": "2026-10-07T00:00:00Z",
            "message_type": "telemetry",
        }
    ).encode("utf-8")


def test_parse_mqtt_telemetry_valid(valid_payload: bytes) -> None:
    topic = "tmrp/devices/robot-001/telemetry"
    telemetry_message = parse_mqtt_telemetry(topic, valid_payload)
    assert isinstance(telemetry_message, TelemetryMessage)
    assert telemetry_message.device_id == "robot-001"
    assert telemetry_message.sequence_no == 1


@pytest.mark.parametrize(
    "topic",
    [
        "tmrp/devices",
        "tmrp/devices/robot-001/telemetry/extra",
        "tmrp/other/robot-001/telemetry",
        "tmrp/devices//telemetry",
        "tmrp/devices/robot-001/status",
        "other/devices/robot-001/telemetry",
    ],
)
def test_parse_mqtt_telemetry_invalid_topic(topic: str, valid_payload: bytes) -> None:
    with pytest.raises(
        TelemetryValidationError,
    ):
        parse_mqtt_telemetry(topic, valid_payload)


def test_parse_mqtt_telemetry_topic_id(valid_payload: bytes) -> None:
    with pytest.raises(TelemetryValidationError, match="device_idが一致しません"):
        parse_mqtt_telemetry(
            "tmrp/devices/robot-002/telemetry",
            valid_payload,
        )


@pytest.mark.parametrize(
    "payload",
    [
        b"{}",
        b"not a json",
        json.dumps({"schema_version": "1.0"}).encode("utf-8"),
    ],
)
def test_parse_mqtt_telemetry_invalid_payload(payload: bytes) -> None:
    topic = "tmrp/devices/robot-001/telemetry"
    with pytest.raises(TelemetryValidationError):
        parse_mqtt_telemetry(topic, payload)


def test_parse_mqtt_telemetry_not_utf8() -> None:
    topic = "tmrp/devices/robot-001/telemetry"
    payload = b"\xff"
    with pytest.raises(UnicodeDecodeError):
        parse_mqtt_telemetry(topic, payload)
