import json
from datetime import datetime, timedelta, timezone

import pytest

import myproj.models as models


# test valid telemetry message serialization
def test_telemetry_message_serialization():
    message = models.TelemetryMessage(
        schema_version="1.0",
        device_id="device123",
        sequence_no=1001,
        event_time=datetime.now(timezone.utc),
        message_type=models.MessageType.TELEMETRY,
        battery_percent=75.5,
        temperature_c=22.3,
        network_rssi=-50,
        status_flags=["flag1", "flag2"],
    )

    expected_dict = {
        "schema_version": "1.0",
        "device_id": "device123",
        "sequence_no": 1001,
        "event_time": message.event_time.isoformat(),
        "message_type": models.MessageType.TELEMETRY.value,
        "battery_percent": 75.5,
        "temperature_c": 22.3,
        "network_rssi": -50,
        "status_flags": ["flag1", "flag2"],
    }

    assert message.to_dict() == expected_dict


@pytest.mark.parametrize(
    "event_time", [datetime(2026, 9, 28, 9, 0, tzinfo=timezone(timedelta(hours=9)))]
)
def test_valid_telemetry_event_time(event_time: datetime):
    message = models.TelemetryMessage(
        schema_version="1.0",
        device_id="device123",
        sequence_no=1001,
        event_time=event_time,
        message_type=models.MessageType.TELEMETRY,
    )
    assert message.to_dict()["event_time"] == "2026-09-28T00:00:00+00:00"


def test_to_json_preserves_unicodes_and_null() -> None:
    message = models.TelemetryMessage(
        schema_version="1.0",
        device_id="ロボット-001",
        sequence_no=1001,
        event_time=datetime(2026, 9, 28, tzinfo=timezone.utc),
        message_type=models.MessageType.TELEMETRY,
        battery_percent=None,
        temperature_c=None,
        network_rssi=None,
        status_flags=["フラグ1", "フラグ2"],
    )

    text = message.to_json()
    payload = json.loads(text)

    assert "ロボット-001" in text
    assert payload["device_id"] == "ロボット-001"
    assert payload["battery_percent"] is None
    assert payload == message.to_dict()


def test_to_dict_not_share_status_flags():
    message = models.TelemetryMessage(
        schema_version="1.0",
        device_id="device123",
        sequence_no=1001,
        event_time=datetime(2026, 9, 28, tzinfo=timezone.utc),
        message_type=models.MessageType.TELEMETRY,
        status_flags=["ok"],
    )

    data = message.to_dict()
    flags = data["status_flags"]

    assert isinstance(flags, list)
    flags.append("changed")

    assert flags == ["ok", "changed"]
    assert message.status_flags == ["ok"]


def test_from_dict():
    json_data = {
        "schema_version": "1.0",
        "device_id": "robot-001",
        "sequence_no": 0,
        "event_time": "2024-06-01T12:00:00Z",
        "message_type": "telemetry",
        "battery_percent": 82.5,
        "temperature_c": 41.2,
        "network_rssi": -67,
        "status_flags": ["motor_enabled", "gps_fixed"],
    }
    message = models.TelemetryMessage.from_dict(json_data)

    assert message == models.TelemetryMessage.from_dict(message.to_dict())
