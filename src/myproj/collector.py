from dataclasses import dataclass, field
from typing import Any

import paho.mqtt.client as mqtt
from psycopg import Connection

from myproj.models import TelemetryMessage
from myproj.mqtt_validation import parse_mqtt_telemetry
from myproj.storage import insert_telemetry_batch


@dataclass
class CollectionState:
    conn: Connection[tuple[Any, ...]]
    pending: list[TelemetryMessage] = field(default_factory=list)


def flush_pending(state: CollectionState) -> None:
    if not state.pending:
        return

    conn = state.conn
    total = len(state.pending)
    inserted = insert_telemetry_batch(conn, state.pending)
    print(
        "フラッシュ完了: "
        f"{inserted} 件のメッセージを保存しました,  重複={total - inserted}"
    )
    state.pending.clear()


def collect_telemetry(
    state: CollectionState,
    topic: str,
    payload: bytes,
) -> None:
    telemetry_message = parse_mqtt_telemetry(topic, payload)
    state.pending.append(telemetry_message)
    if len(state.pending) >= 3:
        flush_pending(state)


def run_collector(
    client: mqtt.Client,
    state: CollectionState,
) -> None:
    try:
        client.loop_forever()
    except KeyboardInterrupt:
        print("終了します")
        flush_pending(state)
    finally:
        client.disconnect()
