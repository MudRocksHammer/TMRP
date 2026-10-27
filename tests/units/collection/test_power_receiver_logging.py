import json
from pathlib import Path
from unittest.mock import Mock

import pytest
from loguru import logger

from myproj.collection.power_receiver import PowerReceiver
from myproj.collection.power_validation import PowerValidator

TOPIC = "tmrp/devices/power-meter-001/telemetry"


@pytest.fixture
def logs():
    messages = []
    sink = logger.add(messages.append, serialize=True, format="{message}")
    try:
        yield messages
    finally:
        logger.remove(sink)


@pytest.fixture
def payload():
    return (
        Path(__file__).resolve().parents[3] / "examples/power/valid.json"
    ).read_bytes()


def records(logs):
    return [json.loads(message)["record"] for message in logs]


def receiver(store):
    return PowerReceiver(PowerValidator(frozenset({"power-meter-001"})), store)


@pytest.mark.parametrize("outcome", ["stored", "duplicate", "conflict"])
def test_received_and_result_logs_follow_commit_and_ack(logs, payload, outcome):
    store = Mock()

    def persist(receipt):
        assert [r["message"] for r in records(logs)] == ["telemetry_received"]
        return outcome

    store.store.side_effect = persist

    def ack():
        assert store.store.call_count == 1
        assert [r["message"] for r in records(logs)] == ["telemetry_received"]

    assert (
        receiver(store).handle(TOPIC, payload, qos=1, retain=False, acknowledge=ack)
        == outcome
    )
    received, result = records(logs)
    assert received["message"] == "telemetry_received"
    assert received["extra"]["payload_bytes"] == len(payload)
    assert result["extra"]["receipt_id"] == received["extra"]["receipt_id"]
    assert result["extra"]["device_id"] == "power-meter-001"
    assert result["extra"]["boot_id"] == "training-boot-001"
    assert result["extra"]["sequence_no"] == 1
    assert result["extra"]["outcome"] == outcome
    assert result["extra"]["ack_requested"] is True
    assert result["extra"]["elapsed_ms"] >= 0
    if outcome == "conflict":
        assert result["message"] == "telemetry_rejected"
        assert result["level"]["name"] == "WARNING"
        assert result["extra"]["reason"] == "identity_conflict"
    else:
        assert result["message"] == "telemetry_processed"
        assert result["level"]["name"] == "INFO"


@pytest.mark.parametrize("qos", [0, 1])
def test_rejection_reason_without_payload(logs, qos):
    store, ack = Mock(), Mock()
    body = b"untrusted-secret-payload"
    assert (
        receiver(store).handle(TOPIC, body, qos=qos, retain=False, acknowledge=ack)
        == "rejected"
    )
    result = records(logs)[-1]
    assert result["message"] == "telemetry_rejected"
    assert result["extra"]["reason"] == (
        "unsupported_qos" if qos == 0 else "invalid_json"
    )
    assert result["extra"]["ack_requested"] is (qos == 1)
    assert ack.call_count == qos
    assert body.decode() not in "".join(logs)


@pytest.mark.parametrize(
    "stage", ["persist_telemetry", "persist_rejection", "acknowledge"]
)
def test_failure_logs_distinguish_storage_and_ack_without_secret(logs, payload, stage):
    store, ack = Mock(), Mock()
    store.store.return_value = "stored"
    failure = RuntimeError("password=must-not-appear-in-logs")
    body = payload
    if stage == "persist_telemetry":
        store.store.side_effect = failure
    elif stage == "persist_rejection":
        store.reject.side_effect = failure
        body = b"{"
    else:
        ack.side_effect = failure
    with pytest.raises(RuntimeError) as caught:
        receiver(store).handle(TOPIC, body, qos=1, retain=False, acknowledge=ack)
    assert caught.value is failure
    received, failed = records(logs)
    assert failed["message"] == "telemetry_processing_failed"
    assert failed["level"]["name"] == "ERROR"
    assert failed["extra"]["stage"] == stage
    assert failed["extra"]["persistence_completed"] is (stage == "acknowledge")
    assert failed["extra"]["error_type"] == "RuntimeError"
    assert failed["extra"]["receipt_id"] == received["extra"]["receipt_id"]
    assert "must-not-appear" not in "".join(logs)
    if stage != "acknowledge":
        ack.assert_not_called()
