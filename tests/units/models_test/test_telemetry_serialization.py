import json
from datetime import datetime, timedelta, timezone

import pytest

import myproj.models as models
from myproj.models import TelemetryMessage, TelemetryValidationError


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


@pytest.fixture
def valid_data() -> dict[str, object]:
    return {
        "schema_version": "1.0",
        "device_id": "robot-001",
        "sequence_no": 0,
        "event_time": "2026-09-28T00:00:00Z",
        "message_type": "telemetry",
    }


@pytest.mark.parametrize(
    "field",
    [
        "schema_version",
        "device_id",
        "sequence_no",
        "event_time",
        "message_type",
    ],
)
def test_from_dict_rejects_missing_field(
    valid_data: dict[str, object],
    field: str,
):
    del valid_data[field]

    with pytest.raises(TelemetryValidationError, match=field):
        TelemetryMessage.from_dict(valid_data)


def test_from_dict_unknown_field(valid_data: dict[str, object]) -> None:
    valid_data["unknown_field"] = "value"

    with pytest.raises(TelemetryValidationError, match="unknown_field"):
        TelemetryMessage.from_dict(valid_data)


@pytest.mark.parametrize(
    "sequence_no",
    [-1, True, "1"],
)
def test_from_dict_rejects_invalid_sequence_no(
    valid_data: dict[str, object],
    sequence_no,
):
    valid_data["sequence_no"] = sequence_no

    with pytest.raises(TelemetryValidationError, match="sequence_no"):
        TelemetryMessage.from_dict(valid_data)


@pytest.mark.parametrize(
    "event_time",
    ["2026-09-28T00:00:00", "invalid", 123, True, None],
)
def test_from_dict_rejects_invalid_event_time(
    valid_data: dict[str, object],
    event_time,
):
    valid_data["event_time"] = event_time

    with pytest.raises(TelemetryValidationError, match="event_time"):
        TelemetryMessage.from_dict(valid_data)


@pytest.mark.parametrize(
    "battery_percent",
    [-1, 101, "50", True],
)
def test_from_dict_rejects_invalid_battery_percent(
    valid_data: dict[str, object],
    battery_percent,
):
    valid_data["battery_percent"] = battery_percent

    with pytest.raises(TelemetryValidationError, match="battery_percent"):
        TelemetryMessage.from_dict(valid_data)


@pytest.mark.parametrize(
    "network_rssi",
    [-1000, "strong", True, False],
)
def test_from_dict_rejects_invalid_network_rssi(
    valid_data: dict[str, object],
    network_rssi,
):
    valid_data["network_rssi"] = network_rssi

    with pytest.raises(TelemetryValidationError, match="network_rssi"):
        TelemetryMessage.from_dict(valid_data)


@pytest.mark.parametrize(
    "temperature_c",
    [200, "hot", True],
)
def test_from_dict_rejects_invalid_temperature_c(
    valid_data: dict[str, object],
    temperature_c,
):
    valid_data["temperature_c"] = temperature_c

    with pytest.raises(TelemetryValidationError, match="temperature_c"):
        TelemetryMessage.from_dict(valid_data)


@pytest.mark.parametrize(
    "message_type",
    ["invalid_type", 123, True],
)
def test_from_dict_rejects_invalid_message_type(
    valid_data: dict[str, object],
    message_type,
):
    valid_data["message_type"] = message_type

    with pytest.raises(TelemetryValidationError, match="message_type"):
        TelemetryMessage.from_dict(valid_data)


@pytest.mark.parametrize("status_flags", [None, "ok", ["ok", 123]])
def test_from_dict_rejects_invalid_status_flags(
    valid_data: dict[str, object],
    status_flags,
):
    valid_data["status_flags"] = status_flags

    with pytest.raises(TelemetryValidationError, match="status_flags"):
        TelemetryMessage.from_dict(valid_data)


def test_from_dict_default_fixture(valid_data: dict[str, object]):
    message = TelemetryMessage.from_dict(valid_data)
    assert message.sequence_no == 0
    assert message.battery_percent is None
    assert message.network_rssi is None
    assert message.temperature_c is None
    assert message.status_flags == []


def test_from_dict_does_not_share_status_flags(valid_data: dict[str, object]) -> None:
    flags = ["ok"]
    valid_data["status_flags"] = flags

    message = TelemetryMessage.from_dict(valid_data)
    flags.append("changed")

    assert flags == ["ok", "changed"]
    assert message.status_flags == ["ok"]


@pytest.mark.parametrize("data", [None, [], "invalid"])
def test_from_dict_rejects_non_dict(data: object):
    with pytest.raises(TelemetryValidationError, match="dictionary"):
        TelemetryMessage.from_dict(data)
