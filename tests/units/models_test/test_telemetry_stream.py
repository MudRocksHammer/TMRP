import json

import pytest

from myproj.models import MessageType, TelemetryValidationError
from myproj.stream import iter_telemetry


@pytest.fixture
def valid_line() -> str:
    return json.dumps(
        {
            "device_id": "robot-001",
            "schema_version": "1.0",
            "sequence_no": 1,
            "message_type": MessageType.TELEMETRY.value,
            "event_time": "2026-09-29T00:00:00+00:00",
            "temperature_c": 25.0,
            "network_rssi": -70,
            "status_flags": ["ok"],
        }
    )


def test_iter_telemetry_skips_blank_lines(valid_line: str):
    lines = ["", valid_line, " ", "\n", valid_line]

    message = list(iter_telemetry(lines))

    assert len(message) == 2
    assert all(msg.device_id == "robot-001" for msg in message)


def test_iter_telemetry_rejects_empty_object():
    with pytest.raises(TelemetryValidationError, match="line 1"):
        list(iter_telemetry(["{}"]))


def test_iter_telemetry_reports_line_number(valid_line: str):
    invalid_lines = ["", valid_line, "{"]
    with pytest.raises(TelemetryValidationError, match="line 3"):
        list(iter_telemetry(invalid_lines))


def test_iter_telemetry_processes_lazily(valid_line: str):
    iterator = iter_telemetry([valid_line, "{"])

    first = next(iterator)
    assert first.device_id == "robot-001"

    with pytest.raises(TelemetryValidationError):
        next(iterator)


def test_iter_telemetry_valid(valid_line: str):
    second_data = json.loads(valid_line)
    second_data["device_id"] = "robot-002"
    second_data["sequence_no"] = 2

    lines = [valid_line, json.dumps(second_data)]
    messages = list(iter_telemetry(lines))

    assert len(messages) == 2
    assert [msg.device_id for msg in messages] == [
        "robot-001",
        "robot-002",
    ]
    assert [msg.sequence_no for msg in messages] == [1, 2]
