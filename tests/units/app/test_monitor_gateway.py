import json
import time
from datetime import datetime, timezone
from threading import Thread
from unittest.mock import Mock
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from uuid import uuid4

import pytest

from myproj.app.monitor_gateway import GatewayState, make_server


def telemetry(sequence=1, **changes):
    return {
        "schema_version": "1.0",
        "message_type": "power_telemetry",
        "device_id": "power-meter-001",
        "boot_id": "boot-1",
        "sequence_no": sequence,
        "event_time": datetime.now(timezone.utc).isoformat(),
        "breaker_state": "closed",
        "quality": "good",
        "voltage_ab_v": 400,
        "voltage_bc_v": 400,
        "voltage_ca_v": 400,
        "current_a_a": 85,
        "current_b_a": 85,
        "current_c_a": 85,
        "active_power_kw": 52,
        "frequency_hz": 50,
        **changes,
    }


@pytest.fixture
def state():
    client = Mock()
    client.publish.return_value.rc = 0
    value = GatewayState({"power-meter-001": "breaker-001"}, client)
    value.ready = True
    value.receive(
        "tmrp/devices/power-meter-001/telemetry",
        json.dumps(telemetry()).encode(),
        1,
        False,
    )
    return value


def command(**changes):
    return {
        "command_id": str(uuid4()),
        "device_id": "power-meter-001",
        "equipment_id": "breaker-001",
        "operation": "open_breaker",
        **changes,
    }


def result(request, **changes):
    return {
        "schema_version": "1.0",
        "message_type": "command_result",
        "device_id": request["device_id"],
        "equipment_id": request["equipment_id"],
        "command_id": request["command_id"],
        "status": "completed",
        **changes,
    }


def receive_result(state, value):
    state.receive(
        "tmrp/devices/power-meter-001/command-results",
        json.dumps(value).encode(),
        1,
        False,
    )


def test_forward_and_correlate_device_result(state):
    request = command()
    assert state.send(request)["status"] == "submitted"
    args, kwargs = state.client.publish.call_args
    assert args[0] == "tmrp/devices/power-meter-001/commands"
    payload = json.loads(args[1])
    assert payload["command_id"] == request["command_id"]
    assert payload["equipment_id"] == "breaker-001"
    assert payload["expires_at"] > payload["issued_at"]
    assert kwargs == {"qos": 1, "retain": False}
    receive_result(state, result(request, equipment_id="wrong"))
    assert state.snapshot()["commands"][0]["status"] == "submitted"
    receive_result(state, result(request, status="accepted"))
    assert state.snapshot()["commands"][0]["status"] == "accepted"
    receive_result(state, result(request))
    assert state.snapshot()["commands"][0]["status"] == "completed"
    receive_result(state, result(request, status="accepted"))
    assert state.snapshot()["commands"][0]["status"] == "completed"
    # Only telemetry, not a command receipt, changes the diagram's breaker state.
    assert state.snapshot()["devices"][0]["telemetry"]["breaker_state"] == "closed"


def test_duplicate_command_does_not_execute_twice(state):
    request = command()
    state.send(request)
    state.send(dict(request))
    assert state.client.publish.call_count == 1
    with pytest.raises(ValueError, match="already used"):
        state.send({**request, "operation": "close_breaker"})
    with pytest.raises(ConnectionError, match="pending"):
        state.send(command())


@pytest.mark.parametrize(
    "change",
    [
        {"device_id": "unknown"},
        {"equipment_id": "wrong"},
        {"operation": "reboot"},
        {"command_id": "bad"},
        {"extra": 1},
        {"device_id": []},
    ],
)
def test_reject_invalid_control(state, change):
    with pytest.raises(ValueError):
        state.send(command(**change))
    state.client.publish.assert_not_called()


def test_stale_disconnected_and_old_event_block_control(state):
    state.ready = False
    with pytest.raises(ConnectionError):
        state.send(command())
    state.ready = True
    state.latest["power-meter-001"]["seen"] -= 11
    with pytest.raises(ConnectionError):
        state.send(command())
    state.latest["power-meter-001"]["seen"] = time.monotonic()
    state.latest["power-meter-001"]["telemetry"]["event_time"] = (
        "2000-01-01T00:00:00+00:00"
    )
    assert not state.snapshot()["devices"][0]["online"]


def test_timeout_and_late_receipt(state):
    request = command()
    state.send(request)
    state.commands[request["command_id"]]["deadline"] = time.monotonic() - 1
    assert state.snapshot()["commands"][0]["status"] == "unknown"
    receive_result(state, result(request))
    assert state.snapshot()["commands"][0]["status"] == "completed"


def test_reordered_and_retained_telemetry_not_forwarded(state):
    original = state.snapshot()["devices"][0]["telemetry"]
    state.receive(
        "tmrp/devices/power-meter-001/telemetry",
        json.dumps(telemetry(0)).encode(),
        1,
        False,
    )
    assert state.snapshot()["devices"][0]["telemetry"] == original
    state.receive(
        "tmrp/devices/power-meter-001/telemetry",
        json.dumps(telemetry(2)).encode(),
        1,
        True,
    )
    assert state.snapshot()["devices"][0]["telemetry"] == original


def test_http_auth_control_and_receipt_round_trip(state):
    token = "a-test-token-with-at-least-24-characters"
    server = make_server("127.0.0.1", 0, state, token)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}"
    try:
        with pytest.raises(HTTPError) as exc:
            urlopen(base + "/api/snapshot", timeout=3)
        assert exc.value.code == 401
        headers = {
            "Authorization": "Bearer " + token,
            "Content-Type": "application/json",
        }
        request = command()
        with urlopen(
            Request(base + "/api/commands", json.dumps(request).encode(), headers),
            timeout=3,
        ) as response:
            assert response.status == 202
            assert json.load(response)["command_id"] == request["command_id"]
        receive_result(state, result(request, status="rejected", reason="interlock"))
        with urlopen(
            Request(base + "/api/snapshot", headers=headers), timeout=3
        ) as response:
            body = json.load(response)
            assert body["devices"][0]["online"]
            assert body["commands"][0]["status"] == "rejected"
            assert body["commands"][0]["result"]["reason"] == "interlock"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
