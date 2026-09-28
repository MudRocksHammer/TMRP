from datetime import datetime, timezone

import pytest

from myproj.models import MessageType, TelemetryMessage, TelemetryValidationError


# schema_version valid test
@pytest.mark.parametrize("schema_version", ["1.0"])
def test_valid_telemetry_schema_version(schema_version: str):
    message = TelemetryMessage(
        schema_version=schema_version,
        device_id="device123",
        sequence_no=1001,
        event_time=datetime.now(timezone.utc),
        message_type=MessageType.TELEMETRY,
    )
    assert message.schema_version == schema_version


# schema_version invalid test
@pytest.mark.parametrize("schema_version", ["2.0", None])
def test_invalid_telemetry_schema_version(schema_version: str | None):
    with pytest.raises(
        TelemetryValidationError,
        match="schema_version",
    ):
        TelemetryMessage(
            schema_version=schema_version,
            device_id="device123",
            sequence_no=1001,
            event_time=datetime.now(timezone.utc),
            message_type=MessageType.TELEMETRY,
        )


# device_id valid test
@pytest.mark.parametrize("device_id", ["device123", "abc", "123"])
def test_valid_telemetry_device_id(device_id: str):
    message = TelemetryMessage(
        schema_version="1.0",
        device_id=device_id,
        sequence_no=1001,
        event_time=datetime.now(timezone.utc),
        message_type=MessageType.TELEMETRY,
    )
    assert message.device_id == device_id


# device_id invalid test
@pytest.mark.parametrize("device_id", ["", "   ", None])
def test_invalid_telemetry_device_id(device_id: str | None):
    with pytest.raises(
        TelemetryValidationError,
        match="device_id",
    ):
        TelemetryMessage(
            schema_version="1.0",
            device_id=device_id,
            sequence_no=1001,
            event_time=datetime.now(timezone.utc),
            message_type=MessageType.TELEMETRY,
        )


# sequence_no valid test
@pytest.mark.parametrize("sequence_no", [0, 1, 100, 9999, 999999])
def test_valid_telemetry_sequence_no(sequence_no: int):
    message = TelemetryMessage(
        schema_version="1.0",
        device_id="device123",
        sequence_no=sequence_no,
        event_time=datetime.now(timezone.utc),
        message_type=MessageType.TELEMETRY,
    )
    assert message.sequence_no == sequence_no


# sequence_no invalid test
@pytest.mark.parametrize("sequence_no", [-1, -10])
def test_invalid_telemetry_sequence_no(sequence_no: int):
    with pytest.raises(
        TelemetryValidationError,
        match="sequence_no",
    ):
        TelemetryMessage(
            schema_version="1.0",
            device_id="device123",
            sequence_no=sequence_no,
            event_time=datetime.now(timezone.utc),
            message_type=MessageType.TELEMETRY,
        )


# event_time valid test
@pytest.mark.parametrize("event_time", [datetime.now(timezone.utc)])
def test_valid_telemetry_event_time(event_time: datetime):
    message = TelemetryMessage(
        schema_version="1.0",
        device_id="device123",
        sequence_no=1001,
        event_time=event_time,
        message_type=MessageType.TELEMETRY,
    )
    assert message.event_time == event_time


# event_time invalid test
@pytest.mark.parametrize("event_time", [None, "not a datetime", datetime(2026, 9, 28)])
def test_invalid_telemetry_event_time(event_time):
    with pytest.raises(
        TelemetryValidationError,
        match="event_time",
    ):
        TelemetryMessage(
            schema_version="1.0",
            device_id="device123",
            sequence_no=1001,
            event_time=event_time,
            message_type=MessageType.TELEMETRY,
        )


# message type valid test
@pytest.mark.parametrize("message_type", [MessageType.TELEMETRY])
def test_valid_telemetry_message_type(message_type):
    message = TelemetryMessage(
        schema_version="1.0",
        device_id="device123",
        sequence_no=1001,
        event_time=datetime.now(timezone.utc),
        message_type=message_type,
    )
    assert message.message_type == message_type


# message type invalid test
@pytest.mark.parametrize("message_type", ["telemetry", "not a telemetry"])
def test_invalid_telemetry_message_type(message_type):
    with pytest.raises(
        TelemetryValidationError,
        match="message_type",
    ):
        TelemetryMessage(
            schema_version="1.0",
            device_id="device123",
            sequence_no=1001,
            event_time=datetime.now(timezone.utc),
            message_type=message_type,
        )


# battery valid test
@pytest.mark.parametrize("battery", [82.5, None, 0, 100])
def test_valid_telemetry_battery(battery: float | None):
    message = TelemetryMessage(
        schema_version="1.0",
        device_id="device123",
        sequence_no=1001,
        event_time=datetime.now(timezone.utc),
        message_type=MessageType.TELEMETRY,
        battery_percent=battery,
    )
    assert message.battery_percent == battery


# battery invalid test
@pytest.mark.parametrize("battery", [-1, 101])
def test_invalid_telemetry_battery(battery: float):
    with pytest.raises(
        TelemetryValidationError,
        match="battery_percent",
    ):
        TelemetryMessage(
            schema_version="1.0",
            device_id="device123",
            sequence_no=1001,
            event_time=datetime.now(timezone.utc),
            message_type=MessageType.TELEMETRY,
            battery_percent=battery,
        )


# temperature valid test
@pytest.mark.parametrize("temperature", [-273.15, 0, 100, None])
def test_valid_telemetry_temperature(temperature: float | None):
    message = TelemetryMessage(
        schema_version="1.0",
        device_id="device123",
        sequence_no=1001,
        event_time=datetime.now(timezone.utc),
        message_type=MessageType.TELEMETRY,
        temperature_c=temperature,
    )
    assert message.temperature_c == temperature


# temperature invalid test
@pytest.mark.parametrize("temperature", [-300, 150])
def test_invalid_telemetry_temperature(temperature: float):
    with pytest.raises(
        TelemetryValidationError,
        match="temperature_c",
    ):
        TelemetryMessage(
            schema_version="1.0",
            device_id="device123",
            sequence_no=1001,
            event_time=datetime.now(timezone.utc),
            message_type=MessageType.TELEMETRY,
            temperature_c=temperature,
        )


# rssi valid test
@pytest.mark.parametrize("rssi", [-100, -50, 0, None])
def test_valid_telemetry_rssi(rssi: int | None):
    message = TelemetryMessage(
        schema_version="1.0",
        device_id="device123",
        sequence_no=1001,
        event_time=datetime.now(timezone.utc),
        message_type=MessageType.TELEMETRY,
        network_rssi=rssi,
    )
    assert message.network_rssi == rssi


# rssi invalid test
@pytest.mark.parametrize("rssi", [-150, 10])
def test_invalid_telemetry_rssi(rssi: int):
    with pytest.raises(
        TelemetryValidationError,
        match="network_rssi",
    ):
        TelemetryMessage(
            schema_version="1.0",
            device_id="device123",
            sequence_no=1001,
            event_time=datetime.now(timezone.utc),
            message_type=MessageType.TELEMETRY,
            network_rssi=rssi,
        )


# status_flags valid test
@pytest.mark.parametrize("flags", [["flag1", "flag2"], []])
def test_valid_telemetry_status_flags(flags: list[str] | None):
    message = TelemetryMessage(
        schema_version="1.0",
        device_id="device123",
        sequence_no=1001,
        event_time=datetime.now(timezone.utc),
        message_type=MessageType.TELEMETRY,
        status_flags=flags if flags is not None else [],
    )
    assert message.status_flags == (flags if flags is not None else [])


# status_flags invalid test
@pytest.mark.parametrize("flags", [["flag1", 123], [None], [True], "ok"])
def test_invalid_telemetry_status_flags(flags: list):
    with pytest.raises(
        TelemetryValidationError,
        match="status_flags",
    ):
        TelemetryMessage(
            schema_version="1.0",
            device_id="device123",
            sequence_no=1001,
            event_time=datetime.now(timezone.utc),
            message_type=MessageType.TELEMETRY,
            status_flags=flags,
        )


# status_flags
def test_default_status_flags():
    message = TelemetryMessage(
        schema_version="1.0",
        device_id="device123",
        sequence_no=1001,
        event_time=datetime.now(timezone.utc),
        message_type=MessageType.TELEMETRY,
    )
    assert message.status_flags == []
