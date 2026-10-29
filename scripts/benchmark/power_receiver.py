"""Local MQTT -> PostgreSQL load test; never targets an existing MQTT server.

Requires TMRP_TEST_DSN with CREATE SCHEMA permission. Only the randomly named
schema and child processes created by this run are removed. See docs for limits.
"""

import argparse
import csv
import hashlib
import json
import math
import os
import platform
import shutil
import socket
import subprocess
import sys
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from importlib.metadata import version
from pathlib import Path
from threading import Event, Thread
from urllib.error import HTTPError, URLError
from urllib.request import urlopen
from uuid import uuid4

import paho.mqtt.client as mqtt
import psycopg
from paho.mqtt.enums import CallbackAPIVersion
from psycopg import sql
from psycopg.conninfo import make_conninfo

from myproj.collection.power_validation import load_power_devices
from myproj.persistence.power_storage import initialize_power_schema
from myproj.telemetry.power_simulator import PowerSimulator

ROOT = Path(__file__).resolve().parents[2]
SCENARIOS = (
    "baseline",
    "headroom",
    "growth",
    "stress",
    "burst",
    "soak",
    "mixed",
    "recovery",
    "large_payload",
)


def percentile(values, percent):
    """Nearest-rank percentile; empty observations must not look like zero latency."""
    if not values:
        return None
    return sorted(values)[max(0, math.ceil(len(values) * percent / 100) - 1)]


def assess(result):
    """Project targets, not an industry certification or capacity guarantee."""
    checks = {
        "all_broker_confirmed": result["broker_confirmed"] == result["offered"],
        "exact_database_contents": result["database_matches"],
        "all_outcomes_observed": result["outcomes_match"],
        "no_processing_errors": result["processing_errors"] == 0,
        "receiver_alive_and_ready": result["ready_at_end"],
        "load_generator_kept_up": result["send_lag_p99_ms"] <= 100,
        "receiver_rss_below_256_mib": result["receiver_peak_rss_mib"] < 256,
        "drained_within_30_seconds": result["drain_seconds"] <= 30,
        "clock_drift_below_50_ms": result["clock_drift_ms"] <= 50,
    }
    if result["scenario"] not in {"burst", "recovery"}:
        checks["scheduled_latency_p95_below_500_ms"] = (
            result["scheduled_to_processed_p95_ms"] is not None
            and result["scheduled_to_processed_p95_ms"] <= 500
        )
        checks["scheduled_latency_p99_below_1000_ms"] = (
            result["scheduled_to_processed_p99_ms"] is not None
            and result["scheduled_to_processed_p99_ms"] <= 1000
        )
        checks["no_readiness_failures"] = result["unready_samples"] == 0
        checks["receiver_cpu_below_70_percent_of_one_core"] = (
            result["receiver_cpu_percent_one_core"] < 70
        )
    if result["scenario"] == "burst":
        # The entire burst is intentionally scheduled for the same instant.
        checks.pop("load_generator_kept_up")
        checks["burst_enqueued_within_2_seconds"] = result["send_seconds"] <= 2
    if result["scenario"] == "soak":
        checks["rss_growth_below_10_mib"] = result["receiver_rss_growth_mib"] <= 10
    return checks


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def eventually(predicate, seconds=15):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.02)
    raise TimeoutError("Isolated test component did not become ready")


def health(port):
    try:
        with urlopen(f"http://127.0.0.1:{port}/health/ready", timeout=0.3) as response:
            return json.load(response)
    except (HTTPError, URLError, OSError):
        return {"ready": False, "counts": {}}


def process_usage(pid):
    try:
        fields = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()
        return {
            "cpu_seconds": (int(fields[11]) + int(fields[12]))
            / os.sysconf("SC_CLK_TCK"),
            "rss_mib": int(fields[21]) * os.sysconf("SC_PAGE_SIZE") / 2**20,
        }
    except (FileNotFoundError, ProcessLookupError):
        return {"cpu_seconds": 0, "rss_mib": 0}


def stop_process(process):
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=8)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


@contextmanager
def laboratory(dsn, directory):
    """Own schema, own broker, own receiver; existing services remain running."""
    schema = "perf_power_" + uuid4().hex
    handles, processes = [], []
    with psycopg.connect(dsn, autocommit=True, connect_timeout=5) as admin:
        admin.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
        try:
            scoped = make_conninfo(
                dsn,
                options=f"-c search_path={schema} -c timezone=UTC",
                application_name=schema,
            )
            with psycopg.connect(scoped, autocommit=True) as conn:
                initialize_power_schema(conn)
                mqtt_port, health_port = free_port(), free_port()
                while health_port == mqtt_port:
                    health_port = free_port()
                config = directory / "mosquitto.conf"
                config.write_text(
                    f"listener {mqtt_port} 127.0.0.1\nallow_anonymous true\n"
                    "persistence false\nmax_queued_messages 100000\n"
                    "max_queued_bytes 134217728\nmax_packet_size 32768\n"
                    "log_type error\nlog_type warning\n"
                )

                def spawn(command, log_name, env=None):
                    handle = (directory / log_name).open("wb")
                    handles.append(handle)
                    process = subprocess.Popen(
                        command, stdout=handle, stderr=handle, env=env, cwd=ROOT
                    )
                    processes.append(process)
                    return process

                broker = spawn(["mosquitto", "-c", str(config)], "broker.log")

                def listening():
                    if broker.poll() is not None:
                        raise RuntimeError("Test broker exited")
                    try:
                        with socket.create_connection(("127.0.0.1", mqtt_port), 0.2):
                            return True
                    except OSError:
                        return False

                eventually(listening)
                config = directory / "receiver.toml"
                config.write_text(
                    f'assets = "{ROOT / "examples/power/assets.json"}"\n'
                    f'client_id = "{schema}"\nmqtt_port = {mqtt_port}\n'
                    f"health_port = {health_port}\n"
                )

                def start_receiver():
                    process = spawn(
                        [
                            sys.executable,
                            "-m",
                            "myproj.app.receiver",
                            "--config",
                            str(config),
                        ],
                        f"receiver-{len(processes)}.log",
                        {
                            **os.environ,
                            "PYTHONPATH": str(ROOT / "src"),
                            "TMRP_RECEIVER_DSN": scoped,
                        },
                    )

                    def ready():
                        if process.poll() is not None:
                            raise RuntimeError("Test receiver exited")
                        return health(health_port)["ready"]

                    eventually(ready)
                    return process

                receiver = start_receiver()
                backend_pid = conn.execute(
                    "SELECT pid FROM pg_stat_activity "
                    "WHERE application_name=%s AND pid <> pg_backend_pid()",
                    (schema,),
                ).fetchone()[0]
                yield (
                    conn,
                    mqtt_port,
                    health_port,
                    broker,
                    receiver,
                    backend_pid,
                    start_receiver,
                )
        finally:
            for process in reversed(processes):
                stop_process(process)
            for handle in handles:
                handle.close()
            admin.execute(
                sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema))
            )


@contextmanager
def publishers(port, count):
    clients = []
    try:
        for _ in range(count):
            connected = Event()
            client = mqtt.Client(
                callback_api_version=CallbackAPIVersion.VERSION2,
                client_id="perf-sender-" + uuid4().hex,
                protocol=mqtt.MQTTv311,
            )
            client.on_connect = lambda c, u, f, r, p, event=connected: (
                event.set() if not r.is_failure else None
            )
            # Avoid Paho scanning a growing queued-message list for every ACK.
            # The total outstanding messages are still bounded by max_queued.
            client.max_inflight_messages_set(0)
            client.max_queued_messages_set(10000)
            client.connect("127.0.0.1", port)
            clients.append(client)
            client.loop_start()
            if not connected.wait(5):
                raise TimeoutError("Test publisher connection failed")
        yield clients
    finally:
        for client in clients:
            client.disconnect()
            client.loop_stop()


def key(payload):
    return payload["device_id"], payload["boot_id"], payload["sequence_no"]


def run_case(dsn, directory, name, duration, soak_seconds):
    rate = {
        "baseline": 12,
        "headroom": 120,
        "growth": 334,
        "stress": 1000,
        "burst": 0,
        "soak": 12,
        "mixed": 120,
        "recovery": 12,
        "large_payload": 120,
    }[name]
    seconds = soak_seconds if name == "soak" else 10 if name == "recovery" else duration
    count = 3600 if name == "burst" else int(rate * seconds)
    if count > 100000:
        raise ValueError("Local run capped at 100000 messages per scenario")
    devices = sorted(load_power_devices(ROOT / "examples/power/assets.json"))
    simulator = PowerSimulator(devices)
    expected, scheduled, published = {}, {}, {}
    expected_outcomes = {"stored": 0, "duplicate": 0, "conflict": 0, "rejected": 0}
    infos, lags, samples, sizes = [], [], [], []
    with laboratory(dsn, directory) as lab:
        conn, port, health_port, broker, receiver, backend_pid, restart = lab
        if name == "recovery":
            stop_process(receiver)
        with publishers(port, len(devices)) as clients:
            stopped = Event()
            sampler_errors = []

            def sample_resources():
                while not stopped.is_set():
                    state = health(health_port)
                    samples.append(
                        {
                            "elapsed_seconds": time.monotonic() - start,
                            "ready": state["ready"],
                            "offered": len(infos),
                            "completed": sum(state["counts"].values()),
                            **{
                                f"{label}_{metric}": value
                                for label, pid in (
                                    ("receiver", receiver.pid),
                                    ("broker", broker.pid),
                                    ("generator", os.getpid()),
                                    ("db_backend", backend_pid),
                                )
                                for metric, value in process_usage(pid).items()
                            },
                        }
                    )
                    stopped.wait(0.5)

            def monitor():
                try:
                    sample_resources()
                except Exception as exc:
                    sampler_errors.append(type(exc).__name__)

            start = time.monotonic()
            wall_start = time.time()
            sampler = Thread(target=monitor, daemon=True)
            sampler.start()
            try:
                previous = None
                for index in range(count):
                    deadline = start + index / rate if rate else start
                    delay = deadline - time.monotonic()
                    if delay > 0:
                        time.sleep(delay)
                    # Independent of receiver/PUBACK speed: record scheduling delay too.
                    now = time.monotonic()
                    lags.append((now - deadline) * 1000)
                    outcome = "stored"
                    if name == "mixed" and index % 10 in (7, 8, 9):
                        payload = dict(previous)
                        outcome = {7: "duplicate", 8: "conflict", 9: "rejected"}[
                            index % 10
                        ]
                        if outcome == "conflict":
                            payload["active_power_kw"] += 1
                        raw = (
                            b"\xff"
                            if outcome == "rejected"
                            else json.dumps(payload).encode()
                        )
                    else:
                        payload = simulator.next_message(
                            datetime.now(timezone.utc)
                        ).to_dict()
                        previous = payload
                        raw = json.dumps(payload).encode()
                        expected[key(payload)] = payload
                        scheduled[key(payload)] = wall_start + deadline - start
                        published[key(payload)] = time.time()
                    expected_outcomes[outcome] += 1
                    if name == "large_payload":
                        # JSON trailing whitespace is valid; exercise the exact
                        # configured size limit without inventing schema fields.
                        raw = raw.ljust(16384, b" ")
                    sizes.append(len(raw))
                    # One connection per device also preserves ordering between
                    # its original, duplicate and conflicting test messages.
                    info = clients[devices.index(payload["device_id"])].publish(
                        f"tmrp/devices/{payload['device_id']}/telemetry",
                        raw,
                        qos=1,
                        retain=False,
                    )
                    if info.rc != mqtt.MQTT_ERR_SUCCESS:
                        raise RuntimeError("Load generator queue full or disconnected")
                    infos.append(info)
                send_seconds = time.monotonic() - start
                # One bounded timeout for all pending acknowledgments, not per message.
                ack_deadline = time.monotonic() + 10
                for info in infos:
                    info.wait_for_publish(
                        timeout=max(0, ack_deadline - time.monotonic())
                    )
                # Include broker-confirmation wait in normal drain time.
                drain_start = start + send_seconds
                if name == "recovery":
                    drain_start = time.monotonic()
                    receiver = restart()
                    backend_pid = conn.execute(
                        "SELECT pid FROM pg_stat_activity "
                        "WHERE application_name=(SELECT application_name "
                        "FROM pg_stat_activity "
                        "WHERE pid=pg_backend_pid()) AND pid <> pg_backend_pid()"
                    ).fetchone()[0]
                deadline = drain_start + 35
                while time.monotonic() < deadline:
                    if receiver.poll() is not None:
                        break
                    if sum(health(health_port)["counts"].values()) >= count:
                        break
                    time.sleep(0.05)
                drained = time.monotonic() - drain_start
                end_state = health(health_port)
            finally:
                stopped.set()
                sampler.join(timeout=2)
            if sampler.is_alive() or sampler_errors or len(samples) < 2:
                raise RuntimeError("Resource monitoring was incomplete")
            clock_drift_ms = (
                abs((time.time() - wall_start) - (time.monotonic() - start)) * 1000
            )
            ready_at_end = receiver.poll() is None and end_state["ready"]
            # Freeze writes before both DB and log snapshots, including a timed
            # out run; otherwise the two counts represent different instants.
            stop_process(receiver)
            actual = {
                key(row[0]): row[0]
                for row in conn.execute("SELECT payload FROM power_telemetry")
            }
            rejection_counts = dict(
                conn.execute(
                    "SELECT reason, count(*) FROM power_telemetry_rejections "
                    "GROUP BY reason"
                ).fetchall()
            )
            db_bytes = conn.execute(
                "SELECT pg_total_relation_size('power_telemetry') + "
                "pg_total_relation_size('power_telemetry_rejections')"
            ).fetchone()[0]

    # Result timestamps are emitted AFTER COMMIT and the ACK API call. This is
    # an upper-bound proxy for commit completion, not event_time/received_at.
    latencies, service_times, send_latencies, outcomes = [], [], [], {}
    errors = 0
    for path in directory.glob("receiver-*.log"):
        for line in path.open():
            record = json.loads(line)["record"]
            if record["message"] == "telemetry_processing_failed":
                errors += 1
            if record["message"] not in {"telemetry_processed", "telemetry_rejected"}:
                continue
            extra = record["extra"]
            outcome = extra["outcome"]
            outcomes[outcome] = outcomes.get(outcome, 0) + 1
            service_times.append(extra["elapsed_ms"])
            if outcome == "stored":
                identity = key(extra)
                finished = record["time"]["timestamp"]
                latencies.append((finished - scheduled[identity]) * 1000)
                send_latencies.append((finished - published[identity]) * 1000)
    rss = [s["receiver_rss_mib"] for s in samples if s["receiver_rss_mib"] > 0]
    cpu_span = (
        samples[-1]["elapsed_seconds"] - samples[0]["elapsed_seconds"]
        if len(samples) > 1
        else 0
    )
    cpu_percent = (
        100
        * (samples[-1]["receiver_cpu_seconds"] - samples[0]["receiver_cpu_seconds"])
        / cpu_span
        if cpu_span
        else 0
    )
    result = {
        "scenario": name,
        "target_messages_per_second": rate or None,
        "duration_seconds": seconds if rate else 0,
        "connections": len(devices),
        "offered": count,
        "broker_confirmed": sum(i.is_published() for i in infos),
        "stored_rows": len(actual),
        "unstored_rows_at_stop": len(expected) - len(actual),
        "expected_rows": len(expected),
        "database_matches": actual == expected
        and rejection_counts
        == {
            reason: n
            for reason, n in (
                ("invalid_utf8", expected_outcomes["rejected"]),
                ("identity_conflict", expected_outcomes["conflict"]),
            )
            if n
        },
        "outcomes": outcomes,
        "outcomes_match": all(
            outcomes.get(k, 0) == v for k, v in expected_outcomes.items()
        ),
        "processing_errors": errors,
        "ready_at_end": ready_at_end,
        "send_seconds": send_seconds,
        "drain_seconds": drained,
        "offered_per_second": count / send_seconds,
        "stored_per_second_including_drain": len(actual) / (send_seconds + drained),
        "send_lag_p99_ms": percentile(lags, 99),
        "clock_drift_ms": clock_drift_ms,
        "scheduled_to_processed_p95_ms": percentile(latencies, 95),
        "scheduled_to_processed_p99_ms": percentile(latencies, 99),
        "scheduled_to_processed_max_ms": max(latencies, default=None),
        "publish_to_processed_p99_ms": percentile(send_latencies, 99),
        "handler_p99_ms": percentile(service_times, 99),
        "receiver_peak_rss_mib": max(rss, default=0),
        "receiver_rss_growth_mib": (rss[-1] - rss[min(len(rss) - 1, 20)]) if rss else 0,
        "receiver_cpu_percent_one_core": cpu_percent,
        "unready_samples": sum(not s["ready"] for s in samples),
        "max_observed_pending": max(
            (s["offered"] - s["completed"] for s in samples), default=0
        ),
        "database_bytes": db_bytes,
        "receiver_log_bytes": sum(
            p.stat().st_size for p in directory.glob("receiver-*.log")
        ),
        "payload_bytes_mean": sum(sizes) / len(sizes),
    }
    result["checks"] = assess(result)
    result["load_valid"] = result["checks"].get(
        "burst_enqueued_within_2_seconds", result["send_lag_p99_ms"] <= 100
    )
    result["passed"] = all(result["checks"].values())
    with (directory / "samples.csv").open("w") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(samples[0]))
        writer.writeheader()
        writer.writerows(samples)
    (directory / "result.json").write_text(json.dumps(result, indent=2) + "\n")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output", type=Path, required=True, help="New result directory"
    )
    parser.add_argument(
        "--duration", type=int, default=30, help="Load stage duration, 10..60 s"
    )
    parser.add_argument(
        "--soak-seconds", type=int, default=120, help="Short soak, 30..3600 s"
    )
    parser.add_argument("--scenario", choices=SCENARIOS, action="append")
    args = parser.parse_args()
    if not 10 <= args.duration <= 60 or not 30 <= args.soak_seconds <= 3600:
        parser.error("duration must be 10..60; soak-seconds must be 30..3600")
    dsn = os.environ.get("TMRP_TEST_DSN")
    if not dsn or not shutil.which("mosquitto") or sys.platform != "linux":
        parser.error("Linux, Mosquitto and TMRP_TEST_DSN are required")
    args.output = args.output.resolve()
    args.output.mkdir(parents=True, exist_ok=False)
    with psycopg.connect(dsn, autocommit=True, connect_timeout=5) as conn:
        database = dict(
            conn.execute(
                "SELECT name, setting FROM pg_settings WHERE name IN "
                "('server_version', 'fsync', 'synchronous_commit', "
                "'full_page_writes', 'shared_buffers')"
            ).fetchall()
        )
    report = {
        "started_at_utc": datetime.now(timezone.utc).isoformat(),
        "environment": {
            "platform": platform.platform(),
            "python": platform.python_version(),
            "logical_cpus": os.cpu_count(),
            "benchmark_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "meminfo": Path("/proc/meminfo").read_text(),
            "database": database,
            "packages": {p: version(p) for p in ("psycopg", "paho-mqtt", "loguru")},
            "git_head": subprocess.check_output(
                ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
            ).strip(),
        },
        "scope": (
            "local plaintext MQTT, 12 connections, file JSON logging, "
            "shared PostgreSQL; not production acceptance"
        ),
        "results": [],
    }
    for name in args.scenario or SCENARIOS:
        print(f"Starting {name}", flush=True)
        directory = args.output / name
        directory.mkdir()
        try:
            result = run_case(dsn, directory, name, args.duration, args.soak_seconds)
        except Exception as exc:
            # No DSN, passwords or raw exception text in the shareable report.
            result = {
                "scenario": name,
                "passed": False,
                "error_type": type(exc).__name__,
            }
        report["results"].append(result)
        (args.output / "report.json").write_text(json.dumps(report, indent=2) + "\n")
        print(json.dumps(result), flush=True)
    return 0 if all(r["passed"] for r in report["results"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
