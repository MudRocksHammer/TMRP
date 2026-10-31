import socket
import ssl
from dataclasses import replace
from datetime import datetime, timezone
from unittest.mock import Mock

import httpx
import psycopg
import pytest
from fastapi.testclient import TestClient

from myproj.app.control_api import APIServer, create_api, validate_api_settings
from myproj.app.receiver_config import ReceiverConfig, load_receiver_config
from myproj.app.receiver_health import ReceiverHealth
from myproj.persistence.control_store import CommandConflict

READ, CONTROL = "r" * 32, "c" * 32
DEVICE = "power-meter-001"
PREFIX = f"/api/v1/devices/{DEVICE}"


@pytest.fixture
def api():
    config = ReceiverConfig("a", "r", api_command_targets={DEVICE: "breaker-001"})
    store = Mock()
    store.history.return_value = []
    state = ReceiverHealth()
    client = TestClient(
        create_api(config, store, state, frozenset({DEVICE}), READ, CONTROL)
    )
    return client, store, state


def auth(token=READ):
    return {"Authorization": f"Bearer {token}"}


def test_authentication_permissions_and_body_limit(api):
    client, store, _ = api
    assert client.get("/api/v1/devices").status_code == 401
    assert client.get("/api/v1/devices", headers=auth("wrong")).status_code == 401
    assert client.get("/api/v1/devices", headers=auth()).status_code == 200
    body = {"command_id": "cmd-1", "operation": "open_breaker"}
    assert (
        client.post(PREFIX + "/commands", headers=auth(), json=body).status_code == 403
    )
    store.create_command.assert_not_called()
    assert (
        client.post(
            PREFIX + "/commands",
            headers=auth(CONTROL),
            content=b'{"command_id":"a","command_id":"b"}',
        ).status_code
        == 400
    )
    store.create_command.return_value = {"status": "queued"}
    assert (
        client.post(PREFIX + "/commands", headers=auth(CONTROL), json=body).status_code
        == 202
    )

    store.create_command.side_effect = CommandConflict("conflict")
    assert (
        client.post(PREFIX + "/commands", headers=auth(CONTROL), json=body).status_code
        == 409
    )
    assert (
        client.post(
            PREFIX + "/commands", headers=auth(CONTROL), content=b"x" * 16385
        ).status_code
        == 413
    )


def test_history_cursor_keeps_same_timestamp_records(api):
    client, store, _ = api
    timestamp = datetime(2026, 10, 1, tzinfo=timezone.utc)
    rows = [
        {
            "event_time": timestamp,
            "boot_id": "boot-1",
            "sequence_no": n,
            "received_at": timestamp,
            "payload": {"sequence_no": n},
        }
        for n in range(2)
    ]
    store.history.side_effect = [rows, rows[1:]]
    params = {
        "start": "2026-10-01T00:00:00Z",
        "end": "2026-10-02T00:00:00Z",
        "limit": 1,
    }
    first = client.get(PREFIX + "/telemetry", headers=auth(), params=params).json()
    assert first["items"][0]["telemetry"]["sequence_no"] == 0
    assert first["next_cursor"]
    second = client.get(
        PREFIX + "/telemetry",
        headers=auth(),
        params={**params, "cursor": first["next_cursor"]},
    ).json()
    assert second["items"][0]["telemetry"]["sequence_no"] == 1
    assert second["next_cursor"] is None
    assert store.history.call_args.args[-1] == (timestamp, "boot-1", 0)


@pytest.mark.parametrize(
    "change",
    [
        {"operation": "run_shell"},
        {"expires_in_seconds": 301},
        {"expected_state_version": True},
        {"equipment_id": "unauthorized"},
        {"command_id": "../x"},
    ],
)
def test_invalid_commands_do_not_reach_database(api, change):
    client, store, _ = api
    body = {"command_id": "cmd-1", "operation": "open_breaker", **change}
    assert (
        client.post(PREFIX + "/commands", headers=auth(CONTROL), json=body).status_code
        == 422
    )
    store.create_command.assert_not_called()


def test_history_constraints_and_database_outage(api):
    client, store, _ = api
    params = {"start": "2026-10-01T00:00:00Z", "end": "2026-10-02T00:00:00Z"}
    assert client.get(PREFIX + "/telemetry", headers=auth(), params=params).json() == {
        "items": [],
        "next_cursor": None,
    }
    for invalid in (
        {"limit": 1001},
        {"start": "2026-10-01T00:00:00"},
        {"end": "2026-12-01T00:00:00Z"},
        {"cursor": "bad!"},
    ):
        assert (
            client.get(
                PREFIX + "/telemetry", headers=auth(), params={**params, **invalid}
            ).status_code
            == 422
        )
    assert (
        client.get(
            "/api/v1/devices/unknown/telemetry", headers=auth(), params=params
        ).status_code
        == 404
    )
    store.history.side_effect = psycopg.OperationalError("secret connection detail")
    response = client.get(PREFIX + "/telemetry", headers=auth(), params=params)
    assert response.status_code == 503
    assert "secret" not in response.text


@pytest.mark.parametrize(
    "changes",
    [
        {"api_enabled": "true"},
        {"api_enabled": True},
        {"api_cert_file": "a"},
        {"api_port": True},
        {"api_command_targets": []},
        {"api_command_targets": {"a/#": "b"}},
    ],
)
def test_invalid_api_config(changes):
    with pytest.raises(ValueError):
        ReceiverConfig("a", "r", **changes)


def test_config_paths_credentials_and_certificates(
    tmp_path, api_tls_material, monkeypatch
):
    cert, key = api_tls_material
    path = tmp_path / "receiver.toml"
    path.write_text(
        'assets="assets.json"\nclient_id="r"\napi_cert_file="server.crt"\napi_key_file="server.key"\n'
    )
    assert load_receiver_config(path).api_cert_file == str(tmp_path / "server.crt")
    config = ReceiverConfig(
        "a", "r", api_enabled=True, api_cert_file=str(cert), api_key_file=str(key)
    )
    monkeypatch.delenv("TMRP_API_READ_TOKEN", raising=False)
    with pytest.raises(ValueError):
        validate_api_settings(config, frozenset())
    monkeypatch.setenv("TMRP_API_READ_TOKEN", READ)
    monkeypatch.setenv("TMRP_API_CONTROL_TOKEN", CONTROL)
    assert validate_api_settings(config, frozenset()) == (READ, CONTROL)
    with pytest.raises(OSError):
        validate_api_settings(replace(config, api_key_file="missing.key"), frozenset())
    with pytest.raises(ValueError):
        validate_api_settings(
            replace(config, api_command_targets={"unknown": "b"}), frozenset()
        )


def test_real_https_trust_and_stalled_client(api_tls_material):
    cert, key = api_tls_material
    with socket.socket() as reservation:
        reservation.bind(("127.0.0.1", 0))
        port = reservation.getsockname()[1]
    config = ReceiverConfig(
        "a",
        "r",
        api_enabled=True,
        api_port=port,
        api_cert_file=str(cert),
        api_key_file=str(key),
    )
    state = ReceiverHealth()
    state.touch(ready=True)
    server = APIServer(
        config, create_api(config, Mock(), state, frozenset({DEVICE}), READ, CONTROL)
    )
    server.start()
    try:
        # A client that never starts TLS must not block other clients.
        with (
            socket.create_connection(("127.0.0.1", port)),
            httpx.Client(
                verify=ssl.create_default_context(cafile=str(cert)),
                trust_env=False,
                timeout=2,
            ) as client,
        ):
            response = client.get(
                f"https://127.0.0.1:{port}/health/ready", headers=auth()
            )
            assert response.status_code == 200
            assert response.json()["ready"] is True
        with pytest.raises(httpx.ConnectError), httpx.Client(trust_env=False) as client:
            client.get(f"https://127.0.0.1:{port}/health/ready")
        with socket.create_connection(("127.0.0.1", port)) as raw:
            context = ssl.create_default_context(cafile=str(cert))
            with pytest.raises(ssl.SSLCertVerificationError):
                context.wrap_socket(raw, server_hostname="wrong.example")
    finally:
        server.close()
    assert not server.thread.is_alive()
