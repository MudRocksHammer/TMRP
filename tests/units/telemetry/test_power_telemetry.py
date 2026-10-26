import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

from myproj.telemetry.messageType import MessageType
from myproj.telemetry.models import MessageType as LegacyMessageType
from myproj.telemetry.models import TelemetryMessage, TelemetryValidationError
from myproj.telemetry.power import (
    BreakerState,
    MeasurementQuality,
    PowerTelemetry,
    PowerTelemetryValidationError,
)

SAMPLES = Path(__file__).resolve().parents[3] / "examples" / "power"
# 契約の8測定項目。本体の定数とは独立に、検証対象を列挙する。
MEASUREMENTS = (
    "voltage_ab_v",
    "voltage_bc_v",
    "voltage_ca_v",
    "current_a_a",
    "current_b_a",
    "current_c_a",
    "active_power_kw",
    "frequency_hz",
)


@pytest.fixture
def arguments() -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "message_type": MessageType.POWER,
        "device_id": "power-meter-001",
        "boot_id": "training-boot-001",
        "sequence_no": 0,
        "event_time": datetime(2026, 10, 23, tzinfo=timezone.utc),
        "breaker_state": BreakerState.CLOSED,
        "quality": MeasurementQuality.GOOD,
        "voltage_ab_v": 10000,
        "voltage_bc_v": 9990,
        "voltage_ca_v": 10010,
        "current_a_a": 100,
        "current_b_a": 101,
        "current_c_a": 99,
        "active_power_kw": 1500,
        "frequency_hz": 50,
    }


def test_constructor_normalizes_numbers_and_time(arguments):
    arguments["event_time"] = datetime(
        2026, 10, 23, 9, tzinfo=timezone(timedelta(hours=9))
    )
    message = PowerTelemetry(**arguments)
    assert message.event_time == datetime(2026, 10, 23, tzinfo=timezone.utc)
    assert message.event_time.tzinfo is timezone.utc
    assert message.sequence_no == 0
    for name in MEASUREMENTS:
        assert type(getattr(message, name)) is float
        assert getattr(message, name) == arguments[name]


@pytest.mark.parametrize(
    "missing, quality",
    [
        (0, MeasurementQuality.GOOD),
        (1, MeasurementQuality.PARTIAL),
        (7, MeasurementQuality.PARTIAL),
        (8, MeasurementQuality.UNAVAILABLE),
    ],
)
@pytest.mark.parametrize("breaker", list(BreakerState))
def test_quality_depends_on_measurements_not_breaker(
    arguments, missing, quality, breaker
):
    arguments.update({name: None for name in MEASUREMENTS[:missing]})
    arguments.update(quality=quality, breaker_state=breaker)
    message = PowerTelemetry(**arguments)
    assert message.quality is quality
    assert message.breaker_state is breaker
    assert sum(getattr(message, name) is None for name in MEASUREMENTS) == missing


@pytest.mark.parametrize(
    "missing, quality",
    [
        (1, MeasurementQuality.GOOD),
        (8, MeasurementQuality.GOOD),
        (0, MeasurementQuality.PARTIAL),
        (8, MeasurementQuality.PARTIAL),
        (0, MeasurementQuality.UNAVAILABLE),
        (7, MeasurementQuality.UNAVAILABLE),
    ],
)
def test_rejects_inconsistent_quality(arguments, missing, quality):
    arguments.update({name: None for name in MEASUREMENTS[:missing]})
    arguments["quality"] = quality
    with pytest.raises(PowerTelemetryValidationError, match="quality"):
        PowerTelemetry(**arguments)


@pytest.mark.parametrize("name", MEASUREMENTS)
@pytest.mark.parametrize(
    "value",
    [
        True,
        "12.5",
        float("nan"),
        float("inf"),
        -float("inf"),
        pytest.param(10**400, id="integer-overflow"),
    ],
)
def test_rejects_invalid_measurements(arguments, name, value):
    arguments[name] = value
    with pytest.raises(PowerTelemetryValidationError, match=name):
        PowerTelemetry(**arguments)


@pytest.mark.parametrize("name", [n for n in MEASUREMENTS if n != "active_power_kw"])
def test_rejects_negative_unsigned_measurements(arguments, name):
    arguments[name] = -0.01
    with pytest.raises(PowerTelemetryValidationError, match=name):
        PowerTelemetry(**arguments)


def test_zero_is_observed_and_reverse_power_is_allowed(arguments):
    arguments.update({name: 0 for name in MEASUREMENTS})
    arguments["active_power_kw"] = -1500
    message = PowerTelemetry(**arguments)
    assert message.quality is MeasurementQuality.GOOD
    assert message.active_power_kw == -1500.0
    for name in MEASUREMENTS:
        if name != "active_power_kw":
            assert getattr(message, name) == 0.0


@pytest.mark.parametrize("name", ["device_id", "boot_id"])
@pytest.mark.parametrize("value", [None, 123, "", " \t", " id", "id\n"])
def test_rejects_invalid_identifiers(arguments, name, value):
    arguments[name] = value
    with pytest.raises(PowerTelemetryValidationError, match=name):
        PowerTelemetry(**arguments)


@pytest.mark.parametrize(
    "name, value",
    [
        ("schema_version", "2.0"),
        ("schema_version", 1.0),
        ("message_type", "power_telemetry"),
        ("message_type", MessageType.TELEMETRY),
        ("sequence_no", True),
        ("sequence_no", -1),
        ("sequence_no", 1.0),
        ("sequence_no", "1"),
        ("sequence_no", None),
        ("event_time", datetime(2026, 10, 23)),
        ("event_time", None),
        ("event_time", "2026-10-23T00:00:00Z"),
        ("event_time", datetime.min.replace(tzinfo=timezone(timedelta(hours=9)))),
        ("breaker_state", "closed"),
        ("breaker_state", None),
        ("quality", "good"),
        ("quality", None),
    ],
)
def test_constructor_rejects_invalid_metadata(arguments, name, value):
    arguments[name] = value
    with pytest.raises(PowerTelemetryValidationError, match=name):
        PowerTelemetry(**arguments)


@pytest.mark.parametrize("filename", ["valid.json", "partial.json", "unavailable.json"])
def test_sample_round_trip_preserves_all_fields(filename):
    source = (SAMPLES / filename).read_text(encoding="utf-8")
    data = json.loads(source)
    message = PowerTelemetry.from_dict(data)
    expected = dict(data)
    expected["event_time"] = expected["event_time"].replace("Z", "+00:00")
    assert message.to_dict() == expected
    assert json.loads(message.to_json()) == expected
    assert len(message.to_dict()) == 16
    assert message.message_type is MessageType.POWER
    assert PowerTelemetry.from_json(message.to_json()) == message
    assert PowerTelemetry.from_json(source) == message
    assert data == json.loads(source)  # 入力辞書を変更しない。


@pytest.mark.parametrize(
    "filename, reason",
    [
        ("negative-current.json", "current_a_a"),
        ("boolean-measurement.json", "current_a_a"),
        ("boolean-sequence.json", "sequence_no"),
        ("inconsistent-quality.json", "quality"),
        ("missing-timezone.json", "event_time"),
        ("unknown-field.json", "Unknown fields"),
        ("invalid-breaker-state.json", "breaker_state"),
        ("missing-measurement-key.json", "Missing required fields"),
    ],
)
def test_rejects_invalid_samples(filename, reason):
    source = (SAMPLES / "invalid" / filename).read_text(encoding="utf-8")
    with pytest.raises(PowerTelemetryValidationError, match=reason):
        PowerTelemetry.from_json(source)


@pytest.mark.parametrize(
    "name",
    [
        "schema_version",
        "message_type",
        "device_id",
        "boot_id",
        "sequence_no",
        "event_time",
        "breaker_state",
        "quality",
        *MEASUREMENTS,
    ],
)
def test_every_json_key_is_required(arguments, name):
    data = PowerTelemetry(**arguments).to_dict()
    del data[name]
    with pytest.raises(PowerTelemetryValidationError, match="Missing required fields"):
        PowerTelemetry.from_dict(data)


@pytest.mark.parametrize(
    "name, value",
    [
        ("schema_version", None),
        ("device_id", 123),
        ("boot_id", None),
        ("sequence_no", True),
        ("sequence_no", 1.0),
        ("sequence_no", -1),
        ("message_type", "telemetry"),
        ("message_type", ["power_telemetry"]),
        ("breaker_state", []),
        ("quality", {}),
        ("event_time", 0),
        ("event_time", "bad-date"),
        ("event_time", "2026-10-23T00:00:00"),
        ("current_a_a", "100"),
        ("active_power_kw", float("nan")),
        ("frequency_hz", float("inf")),
    ],
)
def test_json_rejects_invalid_values(arguments, name, value):
    data = PowerTelemetry(**arguments).to_dict()
    data[name] = value
    with pytest.raises(PowerTelemetryValidationError, match=name):
        PowerTelemetry.from_json(json.dumps(data))


@pytest.mark.parametrize("source", ["{", "", "null", "[]", "42", '"text"'])
def test_rejects_malformed_json_or_non_objects(source):
    with pytest.raises(PowerTelemetryValidationError):
        PowerTelemetry.from_json(source)


def test_json_normalizes_offset_and_preserves_unicode(arguments):
    data = PowerTelemetry(**arguments).to_dict()
    data.update(event_time="2026-10-23T09:00:00+09:00", device_id="監視機器-001")
    message = PowerTelemetry.from_dict(data)
    assert message.to_dict()["event_time"] == "2026-10-23T00:00:00+00:00"
    assert "監視機器-001" in message.to_json()
    assert PowerTelemetry.from_json(message.to_json()) == message


def test_shared_message_type_keeps_legacy_model_compatible():
    assert LegacyMessageType is MessageType
    arguments = dict(
        schema_version="1.0",
        device_id="robot-001",
        sequence_no=1,
        event_time=datetime(2026, 10, 23, tzinfo=timezone.utc),
        message_type=MessageType.TELEMETRY,
    )
    message = TelemetryMessage(**arguments)
    assert TelemetryMessage.from_json(message.to_json()) == message
    arguments["message_type"] = MessageType.POWER
    with pytest.raises(TelemetryValidationError, match="message_type"):
        TelemetryMessage(**arguments)
