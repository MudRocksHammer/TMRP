"""Real Qt executable + isolated Mosquitto + Python receiver + PostgreSQL.

Run with the TMRP virtualenv and TMRP_TEST_DSN. No existing tables/services change.
"""

import json
import os
import queue
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.request import urlopen
from uuid import uuid4

import paho.mqtt.client as mqtt
import psycopg
from paho.mqtt.enums import CallbackAPIVersion
from psycopg import sql
from psycopg.conninfo import make_conninfo

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from myproj.persistence.power_storage import initialize_power_schema  # noqa: E402
from myproj.telemetry.power import PowerTelemetry  # noqa: E402


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def eventually(predicate, seconds=15):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.05)
    raise AssertionError("Integration condition timed out")


def stop(process):
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


def command(identity, operation="open_breaker"):
    now = datetime.now(timezone.utc)
    return {
        "schema_version": "1.0",
        "message_type": "command",
        "command_id": identity,
        "device_id": "power-meter-001",
        "equipment_id": "breaker-001",
        "operation": operation,
        "issued_at": now.isoformat(),
        "expires_at": (now + timedelta(seconds=60)).isoformat(),
    }


def run():
    dsn = os.environ.get("TMRP_TEST_DSN")
    binary = ROOT / "device-simulator/build/tmrp-device-simulator"
    if not dsn or not binary.exists() or not shutil.which("mosquitto"):
        raise SystemExit("Build the app and set TMRP_TEST_DSN; Mosquitto is required")
    schema = "test_qt_" + uuid4().hex
    processes, handles = [], []
    observer = None
    with tempfile.TemporaryDirectory(prefix="tmrp-qt-integration-") as temp:
        folder = Path(temp)
        with psycopg.connect(dsn, autocommit=True) as admin:
            admin.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
            try:
                scoped = make_conninfo(dsn, options=f"-c search_path={schema}")
                with psycopg.connect(scoped, autocommit=True) as database:
                    initialize_power_schema(database)
                    ports = set()
                    while len(ports) < 3:
                        ports.add(free_port())
                    port, tls_port, health_port = sorted(ports)
                    subprocess.run(
                        [
                            "openssl",
                            "req",
                            "-x509",
                            "-newkey",
                            "rsa:2048",
                            "-nodes",
                            "-days",
                            "1",
                            "-keyout",
                            str(folder / "server.key"),
                            "-out",
                            str(folder / "ca.crt"),
                            "-subj",
                            "/CN=localhost",
                            "-addext",
                            "subjectAltName=DNS:localhost,IP:127.0.0.1",
                        ],
                        check=True,
                        capture_output=True,
                        timeout=15,
                    )
                    config = folder / "mosquitto.conf"
                    config.write_text(
                        f"listener {port} 127.0.0.1\n"
                        "allow_anonymous true\npersistence false\n"
                        f"listener {tls_port} 127.0.0.1\nallow_anonymous true\n"
                        f"certfile {folder / 'ca.crt'}\n"
                        f"keyfile {folder / 'server.key'}\n"
                    )

                    def spawn(args, name, env=None):
                        log = (folder / name).open("wb")
                        handles.append(log)
                        process = subprocess.Popen(
                            args, stdout=log, stderr=log, env=env
                        )
                        processes.append(process)
                        return process

                    broker = spawn(["mosquitto", "-c", str(config)], "broker.log")

                    def listening():
                        assert broker.poll() is None
                        try:
                            with socket.create_connection(("127.0.0.1", port), 0.2):
                                return True
                        except OSError:
                            return False

                    eventually(listening)
                    server_config = folder / "receiver.toml"
                    server_config.write_text(
                        f'assets="{ROOT / "examples/power/assets.json"}"\n'
                        f'client_id="qt-integration-receiver"\nmqtt_port={port}\nhealth_port={health_port}\n'
                    )
                    receiver = spawn(
                        [
                            sys.executable,
                            "-m",
                            "myproj.app.receiver",
                            "--config",
                            str(server_config),
                        ],
                        "receiver.log",
                        {
                            **os.environ,
                            "PYTHONPATH": str(ROOT / "src"),
                            "TMRP_RECEIVER_DSN": scoped,
                        },
                    )

                    def ready():
                        assert receiver.poll() is None, (
                            folder / "receiver.log"
                        ).read_text()
                        try:
                            with urlopen(
                                f"http://127.0.0.1:{health_port}/health/ready",
                                timeout=0.3,
                            ) as response:
                                return response.status == 200
                        except OSError:
                            return False

                    eventually(ready)
                    inbox = queue.Queue()
                    observer = mqtt.Client(
                        callback_api_version=CallbackAPIVersion.VERSION2
                    )
                    observer.on_connect = lambda c, u, f, r, p: c.subscribe(
                        "tmrp/devices/+/+", qos=1
                    )
                    observer.on_message = lambda c, u, m: inbox.put(
                        (m.topic, bytes(m.payload))
                    )
                    observer.connect("127.0.0.1", port)
                    observer.loop_start()

                    def wait_message(predicate, seconds=20):
                        deadline = time.monotonic() + seconds
                        while time.monotonic() < deadline:
                            assert app.poll() is None, (folder / "app.log").read_text()
                            try:
                                topic, payload = inbox.get(timeout=0.2)
                            except queue.Empty:
                                continue
                            value = json.loads(payload)
                            if predicate(topic, value):
                                return value
                        raise AssertionError("Expected MQTT message was not received")

                    app_config = folder / "fleet.json"
                    app_config.write_text(
                        json.dumps(
                            {
                                "schema_version": "1.0",
                                "devices": [
                                    {
                                        "name": f"test-{number}",
                                        "device_id": f"power-meter-{number:03}",
                                        "equipment_id": f"breaker-{number:03}",
                                        "host": "127.0.0.1",
                                        "port": port if number == 1 else tls_port,
                                        "source_ip": "127.0.0.1",
                                        "username": "",
                                        "tls": number == 2,
                                        "ca_file": str(folder / "ca.crt"),
                                        "rate_hz": 2,
                                        "operation_delay_ms": 100,
                                    }
                                    for number in (1, 2)
                                ],
                            }
                        )
                    )
                    env = {**os.environ, "QT_QPA_PLATFORM": "offscreen"}
                    prefix = ROOT / "device-simulator/.deps/qt/usr"
                    if prefix.exists():
                        env["LD_LIBRARY_PATH"] = ":".join(
                            str(prefix / subdir)
                            for subdir in (
                                "lib/x86_64-linux-gnu",
                                "lib/x86_64-linux-gnu/libproxy",
                            )
                        )
                        env["QT_PLUGIN_PATH"] = str(
                            prefix / "lib/x86_64-linux-gnu/qt6/plugins"
                        )

                    def start_app():
                        return spawn(
                            [
                                str(binary),
                                "--fleet",
                                str(app_config),
                                "--state-dir",
                                str(folder / "state"),
                                "--headless",
                                "--auto-connect",
                                "--auto-send",
                            ],
                            "app.log",
                            env,
                        )

                    app = start_app()
                    first = wait_message(
                        lambda t, v: (
                            t.endswith("/telemetry")
                            and v["device_id"] == "power-meter-001"
                        )
                    )
                    PowerTelemetry.from_dict(first)
                    assert first["breaker_state"] == "closed"
                    eventually(
                        lambda: (
                            database.execute(
                                "SELECT count(*) FROM power_telemetry"
                            ).fetchone()[0]
                            > 0
                        )
                    )

                    def send(value):
                        info = observer.publish(
                            f"tmrp/devices/{value['device_id']}/commands",
                            json.dumps(value),
                            qos=1,
                        )
                        info.wait_for_publish(timeout=3)
                        assert info.is_published()

                    def result(identity, status, device="power-meter-001"):
                        return wait_message(
                            lambda t, v: (
                                t.endswith("/command-results")
                                and v["command_id"] == identity
                                and v["status"] == status
                                and v["device_id"] == device
                            )
                        )

                    opening = command("open-1")
                    send(opening)
                    result("open-1", "accepted")
                    completed = result("open-1", "completed")
                    assert completed["breaker_state"] == "open"
                    opened = wait_message(
                        lambda t, v: (
                            t.endswith("/telemetry") and v["breaker_state"] == "open"
                        )
                    )
                    PowerTelemetry.from_dict(opened)
                    assert opened["current_a_a"] == opened["active_power_kw"] == 0
                    assert opened["voltage_ab_v"] == 10000
                    second = wait_message(
                        lambda t, v: (
                            t.endswith("/telemetry")
                            and v["device_id"] == "power-meter-002"
                        )
                    )
                    assert second["breaker_state"] == "closed"
                    assert second["boot_id"] != first["boot_id"]
                    PowerTelemetry.from_dict(second)
                    # Same command_id is independent on different equipment.
                    send(
                        {
                            **opening,
                            "device_id": "power-meter-002",
                            "equipment_id": "breaker-002",
                            "operation": "close_breaker",
                        }
                    )
                    assert (
                        result("open-1", "completed", "power-meter-002")[
                            "state_version"
                        ]
                        == 0
                    )
                    send(opening)
                    assert (
                        result("open-1", "completed")["state_version"]
                        == completed["state_version"]
                    )
                    send({**opening, "operation": "close_breaker"})
                    assert (
                        result("open-1", "rejected")["reason"] == "command_id_conflict"
                    )
                    stop(app)
                    app = start_app()
                    restarted = wait_message(
                        lambda t, v: (
                            t.endswith("/telemetry")
                            and v["device_id"] == "power-meter-001"
                            and v["boot_id"] != first["boot_id"]
                        )
                    )
                    assert restarted["breaker_state"] == "open"
                    send(opening)
                    assert (
                        result("open-1", "completed")["state_version"]
                        == completed["state_version"]
                    )
                    closing = command("close-2", "close_breaker")
                    send(closing)
                    assert result("close-2", "completed")["breaker_state"] == "closed"
                    # Exercise the documented command helper and identical retry.
                    helper = ROOT / "device-simulator/scripts/send_command.py"
                    saved = folder / "helper-command.json"
                    for arguments in (
                        ["--operation", "close_breaker", "--save-command", str(saved)],
                        ["--command-file", str(saved)],
                    ):
                        response = subprocess.run(
                            [
                                sys.executable,
                                str(helper),
                                "--port",
                                str(port),
                                *arguments,
                            ],
                            capture_output=True,
                            text=True,
                            timeout=20,
                        )
                        assert response.returncode == 0, response.stderr
                        assert '"status": "completed"' in response.stdout
                    # Broker restart: both the C++ client and Python receiver reconnect.
                    stop(broker)
                    time.sleep(1)
                    while not inbox.empty():
                        inbox.get_nowait()
                    broker = spawn(
                        ["mosquitto", "-c", str(config)], "broker-restarted.log"
                    )
                    eventually(listening)
                    wait_message(
                        lambda t, v: (
                            t.endswith("/status")
                            and v["device_id"] == "power-meter-001"
                            and v["online"]
                        )
                    )
                    reconnected = wait_message(
                        lambda t, v: (
                            t.endswith("/telemetry")
                            and v["device_id"] == "power-meter-001"
                            and v["sequence_no"] > restarted["sequence_no"]
                        )
                    )
                    assert reconnected["boot_id"] == restarted["boot_id"]
                    eventually(ready)
                    send(command("after-reconnect"))
                    assert (
                        result("after-reconnect", "completed")["breaker_state"]
                        == "open"
                    )
                    eventually(
                        lambda: (
                            database.execute(
                                "SELECT count(*) FROM power_telemetry "
                                "WHERE payload->>'breaker_state'='open'"
                            ).fetchone()[0]
                            > 0
                        )
                    )
                    assert (
                        database.execute(
                            "SELECT count(*) FROM power_telemetry_rejections"
                        ).fetchone()[0]
                        == 0
                    )
                    assert (
                        database.execute(
                            "SELECT count(DISTINCT device_id) FROM power_telemetry"
                        ).fetchone()[0]
                        == 2
                    )
                    print(
                        "PASS: two independent Qt devices (plain MQTT + TLS) "
                        "-> Python receiver -> PostgreSQL; "
                        "commands, duplicates, conflicts, restart and broker recovery"
                    )
            finally:
                if observer:
                    observer.disconnect()
                    observer.loop_stop()
                for process in reversed(processes):
                    stop(process)
                for log in handles:
                    log.close()
                admin.execute(
                    sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema))
                )


if __name__ == "__main__":
    run()
