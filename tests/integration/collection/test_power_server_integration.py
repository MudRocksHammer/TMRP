import json
import os
import shutil
import socket
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
from urllib.error import HTTPError, URLError
from urllib.request import urlopen
from uuid import uuid4

import psycopg
import pytest
from paho.mqtt import publish
from psycopg import sql
from psycopg.conninfo import make_conninfo

from myproj.collection.power_receiver import PowerReceiver
from myproj.collection.power_validation import PowerValidator
from myproj.persistence.power_storage import PowerStore, initialize_power_schema

ROOT = Path(__file__).resolve().parents[3]
TOPIC = "tmrp/devices/power-meter-001/telemetry"
NOW = datetime(2026, 10, 27, tzinfo=timezone.utc)


def eventually(predicate, timeout=12):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.05)
    raise AssertionError("Condition not met before deadline")


@pytest.fixture
def power_db(sample_dsn):
    schema = "test_power_" + uuid4().hex
    with psycopg.connect(sample_dsn, autocommit=True) as admin:
        admin.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
        scoped_dsn = make_conninfo(
            sample_dsn, options=f"-c search_path={schema} -c timezone=UTC"
        )
        try:
            with psycopg.connect(scoped_dsn, autocommit=True) as conn:
                initialize_power_schema(conn)
                yield scoped_dsn, conn
        finally:
            admin.execute(
                sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema))
            )


@pytest.fixture
def sample():
    return json.loads((ROOT / "examples/power/valid.json").read_text())


def receipt(data):
    return PowerValidator(frozenset({"power-meter-001"})).parse(
        TOPIC, json.dumps(data).encode(), received_at=NOW
    )


def test_committed_data_is_visible_before_ack(power_db, sample):
    dsn, conn = power_db
    receiver = PowerReceiver(
        PowerValidator(frozenset({"power-meter-001"})), PowerStore(conn), lambda: NOW
    )
    events = []

    def ack():
        with psycopg.connect(dsn) as observer:
            row = observer.execute(
                "SELECT payload, received_at FROM power_telemetry"
            ).fetchone()
        assert row == (receipt(sample).message.to_dict(), NOW)
        events.append("ack")

    assert (
        receiver.handle(
            TOPIC, json.dumps(sample).encode(), qos=1, retain=False, acknowledge=ack
        )
        == "stored"
    )
    assert events == ["ack"]


def test_duplicate_conflict_out_of_order_and_new_boot(power_db, sample):
    dsn, conn = power_db
    store = PowerStore(conn)
    assert store.store(receipt(sample)) == "stored"
    same = {**sample, "event_time": "2026-10-23T09:00:00+09:00"}
    # 別の接続でも重複を識別でき、プロセス内キャッシュへ依存しない。
    with psycopg.connect(dsn, autocommit=True) as fresh:
        assert PowerStore(fresh).store(receipt(same)) == "duplicate"
    assert store.store(receipt({**sample, "active_power_kw": 999})) == "conflict"
    assert store.store(receipt({**sample, "sequence_no": 0})) == "stored"
    assert store.store(receipt({**sample, "boot_id": "new-boot"})) == "stored"
    assert conn.execute("SELECT count(*) FROM power_telemetry").fetchone()[0] == 3
    assert (
        conn.execute("SELECT reason FROM power_telemetry_rejections").fetchone()[0]
        == "identity_conflict"
    )
    assert (
        conn.execute(
            "SELECT payload FROM power_telemetry WHERE boot_id=%s AND sequence_no=1",
            (sample["boot_id"],),
        ).fetchone()[0]
        == receipt(sample).message.to_dict()
    )


def test_rejection_committed_before_ack_and_next_valid_continues(power_db, sample):
    dsn, conn = power_db
    receiver = PowerReceiver(
        PowerValidator(frozenset({"power-meter-001"})), PowerStore(conn)
    )

    def ack_rejection():
        with psycopg.connect(dsn) as observer:
            assert observer.execute(
                "SELECT reason, payload_bytes FROM power_telemetry_rejections"
            ).fetchone() == ("invalid_utf8", 1)

    assert (
        receiver.handle(TOPIC, b"\xff", qos=1, retain=False, acknowledge=ack_rejection)
        == "rejected"
    )
    assert (
        receiver.handle(
            TOPIC,
            json.dumps(sample).encode(),
            qos=1,
            retain=False,
            acknowledge=lambda: None,
        )
        == "stored"
    )


def test_deferred_commit_failure_never_acknowledges(power_db, sample):
    _, conn = power_db
    conn.execute(
        """
        CREATE FUNCTION fail_commit() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN RAISE EXCEPTION 'test commit failure'; END; $$;
        CREATE CONSTRAINT TRIGGER fail_at_commit AFTER INSERT ON power_telemetry
        DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION fail_commit();
    """,
        prepare=False,
    )
    ack = Mock()
    receiver = PowerReceiver(
        PowerValidator(frozenset({"power-meter-001"})), PowerStore(conn)
    )
    with pytest.raises(psycopg.Error):
        receiver.handle(
            TOPIC, json.dumps(sample).encode(), qos=1, retain=False, acknowledge=ack
        )
    ack.assert_not_called()
    assert conn.execute("SELECT count(*) FROM power_telemetry").fetchone()[0] == 0


def test_ack_failure_retains_data_for_redelivery(power_db, sample):
    _, conn = power_db
    receiver = PowerReceiver(
        PowerValidator(frozenset({"power-meter-001"})), PowerStore(conn)
    )
    with pytest.raises(ConnectionError):
        receiver.handle(
            TOPIC,
            json.dumps(sample).encode(),
            qos=1,
            retain=False,
            acknowledge=Mock(side_effect=ConnectionError("lost")),
        )
    ack = Mock()
    assert (
        receiver.handle(
            TOPIC, json.dumps(sample).encode(), qos=1, retain=False, acknowledge=ack
        )
        == "duplicate"
    )
    ack.assert_called_once()


def test_outer_transaction_is_rejected_before_ack(power_db, sample):
    _, conn = power_db
    receiver = PowerReceiver(
        PowerValidator(frozenset({"power-meter-001"})), PowerStore(conn)
    )
    ack = Mock()
    with conn.transaction():
        with pytest.raises(ValueError, match="outer transaction"):
            receiver.handle(
                TOPIC, json.dumps(sample).encode(), qos=1, retain=False, acknowledge=ack
            )
    ack.assert_not_called()


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.fixture
def broker(tmp_path):
    binary = shutil.which("mosquitto")
    if binary is None:
        pytest.skip("Mosquitto is required for real MQTT integration")
    port = free_port()
    config = tmp_path / "mosquitto.conf"
    config.write_text(
        f"listener {port} 127.0.0.1\nallow_anonymous true\n"
        "persistence false\nmax_packet_size 32768\n"
    )
    process = None
    log = (tmp_path / "broker.log").open("wb")

    def stop():
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)

    def start():
        nonlocal process
        process = subprocess.Popen([binary, "-c", str(config)], stdout=log, stderr=log)

        def listening():
            assert process.poll() is None, "Broker exited"
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                    return True
            except OSError:
                return False

        eventually(listening)

    try:
        start()
        yield SimpleNamespace(port=port, start=start, stop=stop)
    finally:
        stop()
        log.close()


def health_code(port):
    try:
        with urlopen(f"http://127.0.0.1:{port}/health/ready", timeout=1) as response:
            return response.status
    except HTTPError as exc:
        return exc.code
    except (URLError, OSError):
        return 0


@pytest.fixture
def server(tmp_path, power_db, broker):
    dsn, _ = power_db
    port = free_port()
    config = tmp_path / "receiver.toml"
    config.write_text(
        f'assets = "{ROOT / "examples/power/assets.json"}"\n'
        f'client_id = "integration-receiver"\nmqtt_port = {broker.port}\n'
        f"health_port = {port}\n"
    )
    processes = []

    def start():
        log_path = tmp_path / f"receiver-{len(processes)}.log"
        log = log_path.open("wb")
        process = subprocess.Popen(
            [
                "bash",
                str(ROOT / "scripts/server/start_server.sh"),
                "--config",
                str(config),
                "--init-db",
            ],
            cwd=ROOT,
            env={
                **os.environ,
                "PYTHONPATH": str(ROOT / "src"),
                "TMRP_RECEIVER_DSN": dsn,
                "TMRP_PYTHON": sys.executable,
            },
            stdout=log,
            stderr=log,
        )
        processes.append((process, log))

        def ready():
            assert process.poll() is None, log_path.read_text()
            return health_code(port) == 200

        eventually(ready)
        return process

    try:
        yield SimpleNamespace(start=start, health_port=port, config=config)
    finally:
        for process, log in processes:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=8)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
            log.close()


def send(broker, data):
    payload = data if isinstance(data, bytes) else json.dumps(data).encode()
    publish.single(TOPIC, payload, qos=1, hostname="127.0.0.1", port=broker.port)


def test_real_server_invalid_duplicate_and_offline_delivery(
    server, broker, power_db, sample
):
    _, conn = power_db
    process = server.start()
    send(broker, sample)
    send(broker, b"\xff")
    eventually(
        lambda: (
            conn.execute("SELECT count(*) FROM power_telemetry_rejections").fetchone()[
                0
            ]
            == 1
        )
    )
    process.terminate()
    assert process.wait(timeout=8) == 0
    send(broker, sample)
    send(broker, {**sample, "sequence_no": 2})
    process = server.start()
    eventually(
        lambda: conn.execute("SELECT count(*) FROM power_telemetry").fetchone()[0] == 2
    )
    assert health_code(server.health_port) == 200
    process.terminate()
    assert process.wait(timeout=8) == 0


def test_db_failure_no_ack_then_broker_redelivers(server, broker, power_db, sample):
    _, conn = power_db
    conn.execute(
        "ALTER TABLE power_telemetry "
        "ADD CONSTRAINT fail_second CHECK (sequence_no <> 2)"
    )
    process = server.start()
    send(broker, sample)
    eventually(
        lambda: conn.execute("SELECT count(*) FROM power_telemetry").fetchone()[0] == 1
    )
    send(broker, {**sample, "sequence_no": 2})
    assert process.wait(timeout=8) == 1
    assert conn.execute("SELECT count(*) FROM power_telemetry").fetchone()[0] == 1
    conn.execute("ALTER TABLE power_telemetry DROP CONSTRAINT fail_second")
    # 送信側から再送しない。未ACKの2件目が同じ永続セッションへ再配送される。
    process = server.start()
    eventually(
        lambda: conn.execute("SELECT count(*) FROM power_telemetry").fetchone()[0] == 2
    )
    process.terminate()
    assert process.wait(timeout=8) == 0


def test_broker_restart_readiness_and_reconnect(server, broker, power_db, sample):
    _, conn = power_db
    process = server.start()
    broker.stop()
    eventually(lambda: health_code(server.health_port) == 503)
    broker.start()
    eventually(lambda: health_code(server.health_port) == 200)
    send(broker, sample)
    eventually(
        lambda: conn.execute("SELECT count(*) FROM power_telemetry").fetchone()[0] == 1
    )
    process.terminate()
    assert process.wait(timeout=8) == 0


def test_continuous_simulator_twelve_devices_at_one_hz(server, power_db, tmp_path):
    _, conn = power_db
    receiver = server.start()
    started = time.monotonic()
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/mqtt/simulate_power.py"),
            "--config",
            str(server.config),
            "--cycles",
            "2",
        ],
        cwd=tmp_path,
        env={**os.environ, "PYTHONPATH": str(ROOT / "src")},
        capture_output=True,
        text=True,
        timeout=25,
    )
    assert result.returncode == 0, result.stderr
    assert "'broker_confirmed': 24" in result.stderr
    assert time.monotonic() - started >= 1.8
    eventually(
        lambda: conn.execute("SELECT count(*) FROM power_telemetry").fetchone()[0] == 24
    )
    rows = conn.execute(
        "SELECT device_id, min(sequence_no), max(sequence_no), count(*) "
        "FROM power_telemetry GROUP BY device_id"
    ).fetchall()
    assert len(rows) == 12
    assert all(row[1:] == (0, 1, 2) for row in rows)
    assert (
        conn.execute("SELECT count(*) FROM power_telemetry_rejections").fetchone()[0]
        == 0
    )
    assert (
        health_code(server.health_port) == 200
    )  # 送信器が受信器のclient_idを奪っていない。
    receiver.terminate()
    assert receiver.wait(timeout=8) == 0


def test_simulator_runs_until_terminated(server, power_db, tmp_path):
    _, conn = power_db
    receiver = server.start()
    log_path = tmp_path / "simulator.log"
    with log_path.open("wb") as log:
        process = subprocess.Popen(
            [
                sys.executable,
                str(ROOT / "scripts/mqtt/simulate_power.py"),
                "--config",
                str(server.config),
                "--rate-hz",
                "2",
            ],
            cwd=tmp_path,
            env={**os.environ, "PYTHONPATH": str(ROOT / "src")},
            stdout=log,
            stderr=log,
        )
        try:
            eventually(
                lambda: (
                    conn.execute("SELECT count(*) FROM power_telemetry").fetchone()[0]
                    >= 30
                )
            )
            assert process.poll() is None
            process.terminate()
            assert process.wait(timeout=8) == 0
        finally:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=5)
    assert "simulator_stopped" in log_path.read_text()
    receiver.terminate()
    assert receiver.wait(timeout=8) == 0
