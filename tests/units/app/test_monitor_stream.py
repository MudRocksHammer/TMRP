from contextlib import ExitStack
from unittest.mock import Mock

import psycopg
import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from myproj.app.control_api import create_api
from myproj.app.receiver_config import ReceiverConfig
from myproj.app.receiver_health import ReceiverHealth

READ, CONTROL = "r" * 32, "c" * 32


@pytest.fixture
def api():
    store = Mock()
    store.monitor_snapshot.side_effect = lambda *args: {
        "devices": [{"device_id": "meter-1", "online": True}],
        "commands": [],
    }
    health = ReceiverHealth()
    health.touch(ready=True)
    config = ReceiverConfig("a", "r", api_command_targets={"meter-1": "breaker-1"})
    with TestClient(
        create_api(config, store, health, frozenset({"meter-1"}), READ, CONTROL)
    ) as client:
        yield client, store, health


def headers(token=READ):
    return {"Authorization": "Bearer " + token}


@pytest.mark.parametrize("token", ["", "wrong", "c" * 31])
def test_stream_rejects_bad_credentials(api, token):
    client, store, _ = api
    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect("/api/stream", headers=headers(token)):
            pass
    assert exc.value.code == 1008
    store.monitor_snapshot.assert_not_called()


def test_shared_stream_heartbeat_permissions_and_mqtt_disconnect(api):
    client, store, health = api
    with (
        client.websocket_connect("/api/stream", headers=headers()) as reader,
        client.websocket_connect("/api/stream", headers=headers(CONTROL)) as operator,
    ):
        first = reader.receive_json()
        second = operator.receive_json()
        assert first["mqtt_ready"] and first["devices"][0]["online"]
        assert first["control_allowed"] is False
        assert second["control_allowed"] is True
        assert store.monitor_snapshot.call_count == 1
        # Even when nothing changes, a new snapshot keeps the client alive.
        assert reader.receive_json() == first
        operator.receive_json()
        health.touch(ready=False)
        data = reader.receive_json()
        assert not data["mqtt_ready"]
        assert not data["devices"][0]["online"]


def test_db_failure_disconnects_and_client_can_reconnect(api):
    client, store, _ = api
    store.monitor_snapshot.side_effect = psycopg.OperationalError("private DSN")
    with client.websocket_connect("/api/stream", headers=headers()) as socket:
        with pytest.raises(WebSocketDisconnect) as exc:
            socket.receive_json()
        assert exc.value.code == 1013
        assert "private" not in exc.value.reason
    store.monitor_snapshot.side_effect = None
    store.monitor_snapshot.return_value = {"devices": [], "commands": []}
    with client.websocket_connect("/api/stream", headers=headers()) as socket:
        assert socket.receive_json()["mqtt_ready"]


def test_stream_rejects_commands_and_limits_connections(api):
    client, _, _ = api
    with client.websocket_connect("/api/stream", headers=headers(CONTROL)) as socket:
        socket.send_text('{"operation":"open_breaker"}')
        with pytest.raises(WebSocketDisconnect) as exc:
            socket.receive_json()
        assert exc.value.code == 1008
    with ExitStack() as stack:
        for _ in range(16):
            stack.enter_context(
                client.websocket_connect("/api/stream", headers=headers())
            )
        with pytest.raises(WebSocketDisconnect) as exc:
            with client.websocket_connect("/api/stream", headers=headers()):
                pass
        assert exc.value.code == 1013
