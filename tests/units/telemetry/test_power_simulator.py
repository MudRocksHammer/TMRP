from datetime import datetime, timezone
from threading import Event
from unittest.mock import Mock, patch

import pytest

from myproj.app.receiver_config import ReceiverConfig
from myproj.collection.power_publisher import PowerPublisher
from myproj.telemetry.power import PowerTelemetry
from myproj.telemetry.power_simulator import (
    PowerSimulator,
    next_deadline,
    validate_rate,
)

NOW = datetime(2026, 10, 27, tzinfo=timezone.utc)


def test_twelve_devices_sequence_and_round_trip():
    devices = [f"power-meter-{index:03d}" for index in range(1, 13)]
    simulator = PowerSimulator(devices, boot_id="test-boot")
    messages = [simulator.next_message(NOW) for _ in range(36)]
    assert len(messages) == 36
    assert [message.device_id for message in messages] == devices * 3
    for device in devices:
        assert [m.sequence_no for m in messages if m.device_id == device] == [0, 1, 2]
    for message in messages:
        assert message.boot_id == "test-boot"
        assert PowerTelemetry.from_json(message.to_json()) == message
    assert simulator.device_ids == tuple(devices)


def test_seed_and_boot_sessions():
    first = PowerSimulator(["a"], seed=42, boot_id="boot")
    second = PowerSimulator(["a"], seed=42, boot_id="boot")
    other = PowerSimulator(["a"], seed=43, boot_id="boot")
    message = first.next_message(NOW)
    assert message == second.next_message(NOW)
    assert message.current_a_a != other.next_message(NOW).current_a_a
    assert PowerSimulator(["a"]).boot_id != PowerSimulator(["a"]).boot_id


@pytest.mark.parametrize("ids", [[], ["a", "a"], [""], ["a/b"], ["+"]])
def test_invalid_devices(ids):
    with pytest.raises(ValueError):
        PowerSimulator(ids)


@pytest.mark.parametrize("rate", [0, -1, True, "1", float("nan"), float("inf")])
def test_invalid_rate(rate):
    with pytest.raises(ValueError):
        validate_rate(rate)


def test_default_rate_spacing_and_no_catch_up_burst():
    interval = 1 / (12 * validate_rate(1.0))
    deadline = 0.0
    for _ in range(12):
        deadline = next_deadline(deadline, deadline + 0.01, interval)
    assert deadline == pytest.approx(1.0)
    assert next_deadline(1.0, 100.0, interval) == pytest.approx(100 + interval)


def test_reconnect_retries_exact_same_event(monkeypatch):
    publisher = PowerPublisher(ReceiverConfig("a", "sim"), client_id="sim-1")
    stop = Event()
    monkeypatch.setattr(stop, "wait", lambda seconds: False)
    message = PowerSimulator(["a"], boot_id="boot").next_message(NOW)
    first, second = Mock(), Mock()
    first.publish.return_value.rc = 4  # MQTT_ERR_NO_CONN
    second.publish.return_value.rc = 0
    second.publish.return_value.is_published.return_value = True
    clients = iter([first, second])

    def connect(stop):
        publisher.client = next(clients)
        return True

    monkeypatch.setattr(publisher, "_connect", connect)
    assert publisher.publish(message, stop)
    assert first.publish.call_args == second.publish.call_args
    assert first.publish.call_args.kwargs == {"qos": 1, "retain": False}
    first.disconnect.assert_called_once()


def test_stop_interrupts_wait_and_unconfirmed_publish():
    stop = Event()
    stop.set()
    publisher = PowerPublisher(ReceiverConfig("a", "sim"), client_id="sim-1")
    assert publisher.wait_until(10**20, stop) is False
    assert publisher.publish(PowerSimulator(["a"]).next_message(NOW), stop) is False


def test_publish_uses_bounded_queue():
    with patch("myproj.collection.power_publisher.mqtt.Client") as factory:
        client = factory.return_value
        client.connect.return_value = 0
        client.is_connected.return_value = True
        publisher = PowerPublisher(ReceiverConfig("a", "sim"), client_id="sim-1")
        assert publisher._connect(Event())
        client.max_queued_messages_set.assert_called_once_with(1)
        client.max_inflight_messages_set.assert_called_once_with(1)
