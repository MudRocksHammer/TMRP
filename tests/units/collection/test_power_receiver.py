import json
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import Mock

import pytest

from myproj.collection.power_receiver import PowerReceiver
from myproj.collection.power_validation import (
    PowerValidator,
    RejectedTelemetry,
    load_power_devices,
)

TOPIC = "tmrp/devices/power-meter-001/telemetry"
NOW = datetime(2026, 10, 27, tzinfo=timezone.utc)
SAMPLES = Path(__file__).resolve().parents[3] / "examples/power"


@pytest.fixture
def payload():
    return (SAMPLES / "valid.json").read_bytes()


@pytest.fixture
def validator():
    return PowerValidator(frozenset({"power-meter-001"}))


def test_metadata_and_observation_time(validator, payload):
    result = validator.parse(TOPIC, payload, received_at=NOW)
    assert result.topic == TOPIC
    assert result.received_at == NOW
    assert result.message.event_time == datetime(2026, 10, 23, tzinfo=timezone.utc)


@pytest.mark.parametrize("name", ["valid.json", "partial.json", "unavailable.json"])
def test_valid_samples(validator, name):
    result = validator.parse(TOPIC, (SAMPLES / name).read_bytes(), received_at=NOW)
    assert result.message.device_id == "power-meter-001"


@pytest.mark.parametrize(
    "path", sorted((SAMPLES / "invalid").glob("*.json")), ids=lambda p: p.stem
)
def test_invalid_samples(validator, path):
    with pytest.raises(RejectedTelemetry):
        validator.parse(TOPIC, path.read_bytes(), received_at=NOW)


@pytest.mark.parametrize(
    "body, code",
    [
        (b"\xff", "invalid_utf8"),
        (b"{", "invalid_json"),
        (b'{"a": 1, "a": 2}', "invalid_json"),
        (b'{"a": NaN}', "invalid_json"),
        (b'{"a": Infinity}', "invalid_json"),
        (b'{"a": "\\ud800"}', "invalid_json"),
        (b'{"a": "\\u0000"}', "invalid_json"),
        pytest.param(b"[" * 33 + b"]" * 33, "invalid_json", id="nested-json"),
        (b"null", "invalid_telemetry"),
        (b"[]", "invalid_telemetry"),
    ],
)
def test_bad_payload(validator, body, code):
    with pytest.raises(RejectedTelemetry) as exc:
        validator.parse(TOPIC, body, received_at=NOW)
    assert exc.value.code == code


@pytest.mark.parametrize(
    "topic, code",
    [
        ("tmrp/devices/+/telemetry", "invalid_topic"),
        ("tmrp/devices/#/telemetry", "invalid_topic"),
        ("tmrp/devices//telemetry", "invalid_topic"),
        ("tmrp/devices/ x/telemetry", "invalid_topic"),
        ("tmrp/devices/x/status", "invalid_topic"),
        ("other/devices/x/telemetry", "invalid_topic"),
        ("tmrp/devices/x/telemetry/extra", "invalid_topic"),
        ("tmrp/devices/x/telemetry", "unknown_device"),
    ],
)
def test_bad_topic(validator, payload, topic, code):
    with pytest.raises(RejectedTelemetry) as exc:
        validator.parse(topic, payload, received_at=NOW)
    assert exc.value.code == code


@pytest.mark.parametrize(
    "kwargs, code",
    [
        ({"qos": 0}, "unsupported_qos"),
        ({"retain": True}, "retained_message"),
    ],
)
def test_delivery_contract(validator, payload, kwargs, code):
    with pytest.raises(RejectedTelemetry) as exc:
        validator.parse(TOPIC, payload, received_at=NOW, **kwargs)
    assert exc.value.code == code


@pytest.mark.parametrize(
    "key, value, code",
    [
        ("device_id", "other", "device_mismatch"),
        ("boot_id", "x" * 129, "metadata_out_of_range"),
        ("sequence_no", 2**63, "metadata_out_of_range"),
    ],
)
def test_server_metadata_limits(validator, payload, key, value, code):
    data = json.loads(payload)
    data[key] = value
    with pytest.raises(RejectedTelemetry) as exc:
        validator.parse(TOPIC, json.dumps(data).encode(), received_at=NOW)
    assert exc.value.code == code


def test_inclusive_byte_limit(payload):
    validator = PowerValidator(frozenset({"power-meter-001"}), len(payload))
    validator.parse(TOPIC, payload, received_at=NOW)
    with pytest.raises(RejectedTelemetry, match="payload_too_large"):
        validator.parse(TOPIC, payload + b" ", received_at=NOW)


def test_registry_and_duplicates(tmp_path):
    assert len(load_power_devices(SAMPLES / "assets.json")) == 12
    data = json.loads((SAMPLES / "assets.json").read_text())
    data["devices"].append(data["devices"][0])
    path = tmp_path / "assets.json"
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="Duplicate"):
        load_power_devices(path)


@pytest.mark.parametrize("invalid", [False, True])
def test_storage_failure_never_acks(validator, payload, invalid):
    store = Mock()
    store.store.side_effect = RuntimeError("commit failed")
    store.reject.side_effect = RuntimeError("commit failed")
    ack = Mock()
    with pytest.raises(RuntimeError):
        PowerReceiver(validator, store).handle(
            TOPIC, b"{" if invalid else payload, qos=1, retain=False, acknowledge=ack
        )
    ack.assert_not_called()


def test_ack_order_and_continues_after_invalid(validator, payload):
    events = []
    store = Mock()
    store.reject.side_effect = lambda *args: events.append("reject_commit")
    store.store.side_effect = lambda *args: events.append("store_commit") or "stored"
    receiver = PowerReceiver(validator, store)
    for body in [b"{", payload]:
        receiver.handle(
            TOPIC, body, qos=1, retain=False, acknowledge=lambda: events.append("ack")
        )
    assert events == ["reject_commit", "ack", "store_commit", "ack"]


def test_qos_zero_rejected_without_ack(validator, payload):
    ack, store = Mock(), Mock()
    assert (
        PowerReceiver(validator, store).handle(
            TOPIC, payload, qos=0, retain=False, acknowledge=ack
        )
        == "rejected"
    )
    ack.assert_not_called()
