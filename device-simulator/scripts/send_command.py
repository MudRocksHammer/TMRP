"""Send one simulated-device command and wait for its application result."""

import argparse
import json
import os
import queue
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Event
from uuid import uuid4

import paho.mqtt.client as mqtt
from paho.mqtt.enums import CallbackAPIVersion


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=18884)
    parser.add_argument("--device-id", default="power-meter-001")
    parser.add_argument("--equipment-id", default="breaker-001")
    parser.add_argument(
        "--operation", choices=["open_breaker", "close_breaker"], default="open_breaker"
    )
    parser.add_argument(
        "--command-file", type=Path, help="Resend an unchanged saved command"
    )
    parser.add_argument(
        "--save-command",
        type=Path,
        help="Save the command for an identical retry (new file)",
    )
    parser.add_argument("--timeout", type=float, default=10)
    parser.add_argument("--username", default="")
    parser.add_argument("--ca-file")
    args = parser.parse_args()
    if not 0 < args.timeout <= 300 or not 1 <= args.port <= 65535:
        parser.error("timeout must be 0..300 seconds; port must be 1..65535")
    if args.host not in {"127.0.0.1", "localhost", "::1"} and not args.ca_file:
        parser.error("Remote connections require --ca-file (or use an SSH tunnel)")
    now = datetime.now(timezone.utc)
    if args.command_file:
        value = json.loads(args.command_file.read_text())
    else:
        value = {
            "schema_version": "1.0",
            "message_type": "command",
            "command_id": str(uuid4()),
            "device_id": args.device_id,
            "equipment_id": args.equipment_id,
            "operation": args.operation,
            "issued_at": now.isoformat(),
            "expires_at": (now + timedelta(seconds=60)).isoformat(),
        }
    for field in ("device_id", "equipment_id", "command_id"):
        if (
            not isinstance(value, dict)
            or not isinstance(value.get(field), str)
            or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", value[field])
        ):
            parser.error(f"Invalid {field}")
    payload = json.dumps(value)
    if args.save_command:
        with args.save_command.open("x") as file:
            file.write(payload + "\n")
    print("command_id=" + value["command_id"], flush=True)
    client = mqtt.Client(callback_api_version=CallbackAPIVersion.VERSION2)
    if args.username:
        client.username_pw_set(args.username, os.environ.get("TMRP_COMMAND_PASSWORD"))
    if args.ca_file:
        client.tls_set(ca_certs=args.ca_file)
    subscribed = Event()
    replies = queue.Queue()
    topic = f"tmrp/devices/{value['device_id']}"

    def on_connect(client, userdata, flags, reason, properties):
        if not reason.is_failure:
            client.subscribe(topic + "/command-results", qos=1)

    def on_subscribe(client, userdata, mid, reasons, properties):
        if reasons and all(reason.value == 1 for reason in reasons):
            subscribed.set()

    def on_message(client, userdata, message):
        try:
            result = json.loads(message.payload)
            if (
                isinstance(result, dict)
                and result.get("command_id") == value["command_id"]
            ):
                replies.put(result)
        except (ValueError, UnicodeError):
            pass

    client.on_connect = on_connect
    client.on_subscribe = on_subscribe
    client.on_message = on_message
    try:
        client.connect(args.host, args.port)
        client.loop_start()
        if not subscribed.wait(5):
            raise TimeoutError("Result subscription not ready")
        info = client.publish(topic + "/commands", payload, qos=1, retain=False)
        info.wait_for_publish(timeout=5)
        if not info.is_published():
            raise TimeoutError("Broker did not confirm publication")
        deadline = time.monotonic() + args.timeout
        while time.monotonic() < deadline:
            try:
                result = replies.get(
                    timeout=min(0.2, max(0, deadline - time.monotonic()))
                )
            except queue.Empty:
                continue
            print(json.dumps(result, ensure_ascii=False), flush=True)
            if result.get("status") in {"completed", "rejected", "failed"}:
                return 0 if result["status"] == "completed" else 1
        raise TimeoutError("Application result not received")
    except (OSError, RuntimeError):
        print(
            "結果を確認できませんでした。保存した同じ指令を再送して確認してください。",
            file=sys.stderr,
        )
        return 2
    finally:
        client.disconnect()
        client.loop_stop()


if __name__ == "__main__":
    raise SystemExit(main())
