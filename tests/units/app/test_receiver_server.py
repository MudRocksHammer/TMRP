import json
from threading import Event
from unittest.mock import Mock, patch
from urllib.error import HTTPError
from urllib.request import urlopen

import pytest

from myproj.app.receiver_config import ReceiverConfig, load_receiver_config
from myproj.app.receiver_health import HealthServer, ReceiverHealth
from myproj.collection.power_mqtt import (
    MQTTConfigurationError,
    PowerMQTTService,
    ReceiptFailure,
)


@pytest.mark.parametrize(
    "changes",
    [
        {"client_id": ""},
        {"mqtt_port": 0},
        {"mqtt_port": True},
        {"health_port": 65536},
        {"keepalive": -1},
        {"max_payload_bytes": 0},
        {"tls": "true"},
        {"mqtt_host": "remote.example"},
        {"cert_file": "cert"},
        {"ca_file": "ca"},
    ],
)
def test_invalid_config(changes):
    with pytest.raises(ValueError):
        ReceiverConfig(
            **{"assets": "assets.json", "client_id": "receiver-1", **changes}
        )


def test_relative_paths_and_unknown_keys(tmp_path):
    path = tmp_path / "receiver.toml"
    text = 'assets = "assets.json"\nclient_id = "receiver-1"\n'
    path.write_text(text)
    config = load_receiver_config(path)
    assert config.assets == str(tmp_path / "assets.json")
    path.write_text(text + 'typo = "wrong"\n')
    with pytest.raises(ValueError, match="Unknown"):
        load_receiver_config(path)


def test_health_endpoints_and_stale_heartbeat():
    state = ReceiverHealth()
    server = HealthServer("127.0.0.1", 0, state)
    server.start()
    base = f"http://127.0.0.1:{server.server.server_port}"
    try:
        with urlopen(base + "/health/live", timeout=2) as response:
            assert response.status == 200
        with pytest.raises(HTTPError) as error:
            urlopen(base + "/health/ready", timeout=2)
        assert error.value.code == 503
        state.touch(ready=True, outcome="stored")
        with urlopen(base + "/health/ready", timeout=2) as response:
            assert json.load(response)["counts"] == {"stored": 1}
        with patch("myproj.app.receiver_health.time.monotonic", return_value=10**20):
            assert state.snapshot()["live"] is False
            assert state.snapshot()["ready"] is False
    finally:
        server.close()


def test_manual_ack_and_tls_setup():
    config = ReceiverConfig(
        "assets.json", "receiver-1", tls=True, mqtt_host="broker.example"
    )
    with patch("myproj.collection.power_mqtt.mqtt.Client") as factory:
        PowerMQTTService(config, Mock(), Mock(), ReceiverHealth())
        assert factory.call_args.kwargs["manual_ack"] is True
        assert factory.call_args.kwargs["clean_session"] is False
        factory.return_value.tls_set.assert_called_once()


def test_subscribe_refused_is_not_ready():
    state = ReceiverHealth()
    service = PowerMQTTService(ReceiverConfig("a", "r"), Mock(), Mock(), state)
    with pytest.raises(MQTTConfigurationError):
        service._on_subscribe(Mock(), None, 1, [Mock(value=128)], None)
    assert state.snapshot()["ready"] is False


def test_callback_storage_failure_propagates_without_ack():
    receiver, client = Mock(), Mock()
    receiver.handle.side_effect = OSError("store unavailable")
    state = ReceiverHealth()
    service = PowerMQTTService(ReceiverConfig("a", "r"), receiver, Mock(), state)
    message = Mock(topic="tmrp/devices/a/telemetry", payload=b"{}", qos=1, retain=False)
    with pytest.raises(ReceiptFailure):
        service._on_message(client, None, message)
    client.ack.assert_not_called()
    assert state.snapshot()["ready"] is False


def test_network_retry_and_stop(monkeypatch):
    stop = Event()
    original_wait = stop.wait
    monkeypatch.setattr(stop, "wait", lambda seconds: original_wait(0.001))
    with patch("myproj.collection.power_mqtt.mqtt.Client") as factory:
        client = factory.return_value
        client.connect.side_effect = [OSError("offline"), 0]
        client.loop.side_effect = lambda **kwargs: stop.set() or 0
        service = PowerMQTTService(
            ReceiverConfig("a", "r"), Mock(), Mock(), ReceiverHealth()
        )
        service.run(stop)
        assert client.connect.call_count == 2
        assert client.disconnect.called


def test_fatal_processing_error_does_not_retry():
    with patch("myproj.collection.power_mqtt.mqtt.Client") as factory:
        client = factory.return_value
        client.connect.return_value = 0
        client.loop.side_effect = ReceiptFailure("DB failure")
        service = PowerMQTTService(
            ReceiverConfig("a", "r"), Mock(), Mock(), ReceiverHealth()
        )
        with pytest.raises(ReceiptFailure):
            service.run(Event())
        assert client.connect.call_count == 1
        assert client.disconnect.called


@pytest.mark.parametrize("database_fails", [False, True])
def test_command_results_commit_before_ack(database_fails):
    actions = []
    commands = Mock()

    def save(result):
        if database_fails:
            raise OSError("database down")
        actions.append("committed")

    commands.save_result.side_effect = save
    client = Mock()
    client.ack.side_effect = lambda *args: actions.append("ack") or 0
    service = PowerMQTTService(
        ReceiverConfig("a", "r"), Mock(), Mock(), ReceiverHealth(), commands=commands
    )
    payload = {
        "schema_version": "1.0",
        "message_type": "command_result",
        "device_id": "power-meter-001",
        "equipment_id": "breaker-001",
        "command_id": "cmd-1",
        "status": "completed",
        "reason": "",
        "state_version": 1,
        "breaker_state": "open",
        "event_time": "2026-10-31T00:00:00Z",
    }
    message = Mock(
        topic="tmrp/devices/power-meter-001/command-results",
        payload=json.dumps(payload).encode(),
        qos=1,
        retain=False,
        mid=7,
    )
    if database_fails:
        with pytest.raises(ReceiptFailure):
            service._on_message(client, None, message)
        client.ack.assert_not_called()
    else:
        service._on_message(client, None, message)
        assert actions == ["committed", "ack"]
