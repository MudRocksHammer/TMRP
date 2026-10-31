"""Authenticated HTTP snapshot/control gateway for the Qt monitor.

Run beside the receiver on the server. MQTT remains the device transport;
this process does not replace the durable receiver or its database.
"""

import argparse
import hmac
import json
import os
import re
import time
from collections import OrderedDict
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import RLock
from typing import Any
from uuid import UUID

import paho.mqtt.client as mqtt
from paho.mqtt.enums import CallbackAPIVersion

from myproj.collection.power_validation import PowerValidator, strict_json

ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}\Z")
TERMINAL = {"completed", "rejected", "failed", "unknown"}


class GatewayState:
    def __init__(self, equipment: dict[str, str], client: Any) -> None:
        if not equipment or any(
            not ID.fullmatch(k) or not isinstance(v, str) or not ID.fullmatch(v)
            for k, v in equipment.items()
        ):
            raise ValueError("Expected device_id -> equipment_id mapping")
        self.equipment = equipment
        self.client = client
        self.validator = PowerValidator(frozenset(equipment))
        self.lock = RLock()
        self.ready = False
        self.latest: dict[str, dict[str, Any]] = {}
        self.commands: OrderedDict[str, dict[str, Any]] = OrderedDict()

    def receive(self, topic: str, payload: bytes, qos: int, retain: bool) -> None:
        if len(payload) > 16384 or retain:
            return
        parts = topic.split("/")
        if len(parts) != 4 or parts[:2] != ["tmrp", "devices"]:
            return
        device = parts[2]
        if device not in self.equipment:
            return
        now = datetime.now(timezone.utc)
        if parts[3] == "telemetry":
            receipt = self.validator.parse(
                topic, payload, received_at=now, qos=qos, retain=retain
            )
            with self.lock:
                old = self.latest.get(device)
                data = receipt.message.to_dict()
                if old:
                    previous = old["telemetry"]
                    if data["event_time"] < previous["event_time"]:
                        return
                    if data["boot_id"] == previous["boot_id"] and (
                        data["sequence_no"] <= previous["sequence_no"]
                    ):
                        return
                self.latest[device] = {
                    "telemetry": data,
                    "received_at": now.isoformat(),
                    "seen": time.monotonic(),
                }
        elif parts[3] == "command-results":
            result = strict_json(payload.decode("utf-8"))
            if not isinstance(result, dict):
                return
            command_id = result.get("command_id")
            if not isinstance(command_id, str):
                return
            with self.lock:
                command = self.commands.get(command_id)
                if (
                    command is None
                    or result.get("schema_version") != "1.0"
                    or result.get("message_type") != "command_result"
                    or result.get("device_id") != device
                    or result.get("equipment_id") != self.equipment[device]
                    or command["request"]["device_id"] != device
                    or result.get("status")
                    not in {"accepted", "completed", "rejected", "failed"}
                    or command["status"] in TERMINAL - {"unknown"}
                ):
                    return
                command["status"] = result["status"]
                command["result"] = result

    def _expire(self) -> None:
        for command in self.commands.values():
            if (
                command["status"] not in TERMINAL
                and time.monotonic() > command["deadline"]
            ):
                command["status"] = "unknown"

    def snapshot(self) -> dict[str, Any]:
        with self.lock:
            self._expire()
            return {
                "mqtt_ready": self.ready,
                "devices": [
                    {
                        "device_id": device,
                        "equipment_id": equipment,
                        "online": self.ready
                        and device in self.latest
                        and time.monotonic() - self.latest[device]["seen"] < 10
                        and abs(
                            (
                                datetime.now(timezone.utc)
                                - datetime.fromisoformat(
                                    self.latest[device]["telemetry"]["event_time"]
                                )
                            ).total_seconds()
                        )
                        < 15,
                        "telemetry": self.latest.get(device, {}).get("telemetry"),
                        "received_at": self.latest.get(device, {}).get("received_at"),
                    }
                    for device, equipment in self.equipment.items()
                ],
                "commands": [
                    {
                        "command_id": key,
                        "device_id": value["request"]["device_id"],
                        "status": value["status"],
                        "result": value.get("result"),
                    }
                    for key, value in self.commands.items()
                ],
            }

    def send(self, request: Any) -> dict[str, Any]:
        if not isinstance(request, dict) or set(request) != {
            "command_id",
            "device_id",
            "equipment_id",
            "operation",
        }:
            raise ValueError("Invalid control request")
        device = request["device_id"]
        if not all(isinstance(v, str) for v in request.values()):
            raise ValueError("Control fields must be strings")
        UUID(request["command_id"])
        if self.equipment.get(device) != request["equipment_id"]:
            raise ValueError("Unknown device/equipment mapping")
        if request["operation"] not in {"open_breaker", "close_breaker"}:
            raise ValueError("Unsupported operation")
        with self.lock:
            self._expire()
            old = self.commands.get(request["command_id"])
            if old:
                if old["request"] != request:
                    raise ValueError("Command ID already used for another request")
                return {"command_id": request["command_id"], "status": old["status"]}
            row = next(
                d for d in self.snapshot()["devices"] if d["device_id"] == device
            )
            if not row["online"]:
                raise ConnectionError("Device offline or telemetry stale")
            if any(
                c["request"]["device_id"] == device and c["status"] not in TERMINAL
                for c in self.commands.values()
            ):
                raise ConnectionError("Device already has a pending command")
            if len(self.commands) >= 500:
                # Never evict commands that may still execute.
                removable = next(
                    (k for k, c in self.commands.items() if c["status"] in TERMINAL),
                    None,
                )
                if removable is None:
                    raise ConnectionError("Command capacity reached")
                del self.commands[removable]
            now = datetime.now(timezone.utc)
            payload = {
                **request,
                "schema_version": "1.0",
                "message_type": "command",
                "issued_at": now.isoformat(),
                "expires_at": (now + timedelta(seconds=15)).isoformat(),
            }
            self.commands[request["command_id"]] = {
                "request": dict(request),
                "status": "submitted",
                "deadline": time.monotonic() + 20,
            }
            info = self.client.publish(
                f"tmrp/devices/{device}/commands",
                json.dumps(payload),
                qos=1,
                retain=False,
            )
            if info.rc != mqtt.MQTT_ERR_SUCCESS:
                self.commands[request["command_id"]]["status"] = "unknown"
                raise ConnectionError("Publish failed; execution outcome unknown")
            return {"command_id": request["command_id"], "status": "submitted"}


def make_server(
    host: str, port: int, state: GatewayState, token: str
) -> ThreadingHTTPServer:
    if len(token) < 24:
        raise ValueError("TMRP_MONITOR_TOKEN must have at least 24 characters")

    class Handler(BaseHTTPRequestHandler):
        def setup(self) -> None:
            self.request.settimeout(3)
            super().setup()

        def reply(self, code: int, value: Any) -> None:
            body = json.dumps(value, allow_nan=False).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def authorized(self) -> bool:
            if not hmac.compare_digest(
                self.headers.get("Authorization", "").encode(),
                ("Bearer " + token).encode(),
            ):
                self.reply(401, {"error": "Unauthorized"})
                return False
            return True

        def do_GET(self) -> None:
            if not self.authorized():
                return
            if self.path != "/api/snapshot":
                self.reply(404, {"error": "Not found"})
                return
            self.reply(200, state.snapshot())

        def do_POST(self) -> None:
            if not self.authorized():
                return
            if self.path != "/api/commands":
                self.reply(404, {"error": "Not found"})
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= 4096:
                    raise ValueError("Invalid body size")
                request = strict_json(self.rfile.read(length).decode("utf-8"))
                self.reply(202, state.send(request))
            except (ValueError, UnicodeError) as exc:
                self.reply(400, {"error": str(exc)})
            except ConnectionError as exc:
                self.reply(409, {"error": str(exc)})

        def log_message(self, format: str, *args: object) -> None:
            pass

    return ThreadingHTTPServer((host, port), Handler)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--equipment", required=True, type=Path)
    parser.add_argument("--host", default="127.0.0.1", choices=["127.0.0.1"])
    parser.add_argument("--port", default=8081, type=int)
    parser.add_argument("--mqtt-host", default="127.0.0.1")
    parser.add_argument("--mqtt-port", default=1883, type=int)
    parser.add_argument("--mqtt-username", default="")
    parser.add_argument("--ca-file")
    args = parser.parse_args()
    if args.mqtt_host not in {"localhost", "127.0.0.1", "::1"} and not args.ca_file:
        parser.error("Remote MQTT requires --ca-file or an SSH tunnel")
    client = mqtt.Client(callback_api_version=CallbackAPIVersion.VERSION2)
    client.max_queued_messages_set(100)
    if args.mqtt_username:
        client.username_pw_set(args.mqtt_username, os.environ.get("TMRP_MQTT_PASSWORD"))
    if args.ca_file:
        client.tls_set(ca_certs=args.ca_file)
    equipment = strict_json(args.equipment.read_text(encoding="utf-8"))
    if not isinstance(equipment, dict):
        parser.error("Equipment file must be an object")
    state = GatewayState(equipment, client)

    def connected(
        client: Any, userdata: Any, flags: Any, reason: Any, properties: Any
    ) -> None:
        if not reason.is_failure:
            client.subscribe(
                [
                    ("tmrp/devices/+/telemetry", 1),
                    ("tmrp/devices/+/command-results", 1),
                ]
            )

    def subscribed(
        client: Any, userdata: Any, mid: Any, reasons: Any, properties: Any
    ) -> None:
        with state.lock:
            state.ready = bool(reasons) and all(r.value == 1 for r in reasons)

    def disconnected(*args: Any) -> None:
        with state.lock:
            state.ready = False

    def received(client: Any, userdata: Any, message: Any) -> None:
        try:
            state.receive(message.topic, message.payload, message.qos, message.retain)
        except (ValueError, UnicodeError, TypeError):
            pass

    client.on_connect = connected
    client.on_subscribe = subscribed
    client.on_disconnect = disconnected
    client.on_message = received
    server = make_server(
        args.host, args.port, state, os.environ.get("TMRP_MONITOR_TOKEN", "")
    )
    client.connect_async(args.mqtt_host, args.mqtt_port, 30)
    client.loop_start()
    try:
        server.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        client.disconnect()
        client.loop_stop()


if __name__ == "__main__":
    main()
