import sys
from dataclasses import dataclass, field
from typing import Any

import paho.mqtt.client as mqtt
import psycopg
from psycopg import Connection

from myproj.models import TelemetryMessage, TelemetryValidationError
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


def on_connect(client, userdata, flags, reason_code, properties):
    if reason_code.is_failure:
        print(f"接続失敗:{reason_code}")
        return

    # tmrp/devices/+/telemetryをQos１で購読する
    client.subscribe("tmrp/devices/+/telemetry", qos=1)
    print("brokerに接続しました")


def on_message(client, userdata, message):
    # トピックと、UTF-8として読み取った本文を表示する
    try:
        telemetry_message = parse_mqtt_telemetry(message.topic, message.payload)
        state = userdata
        state.pending.append(telemetry_message)
        if len(state.pending) >= 3:
            flush_pending(state)
    except (UnicodeDecodeError, TelemetryValidationError) as e:
        print(f"解析失敗: {e}", file=sys.stderr)
        return


def main() -> None:
    with psycopg.connect(
        "host=/var/run/postgresql port=5432 dbname=tmrp_dev user=shou",
        autocommit=True,
        options="-c timezone=UTC",
    ) as conn:
        state = CollectionState(conn=conn)
        client = mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
            userdata=state,
        )
        client.on_connect = on_connect
        client.on_message = on_message

        client.connect("127.0.0.1", 18883, keepalive=60)
        try:
            client.loop_forever()
        except KeyboardInterrupt:
            print("終了します")
            flush_pending(state)
        finally:
            client.disconnect()


if __name__ == "__main__":
    main()
