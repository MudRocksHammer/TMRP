import sys

import paho.mqtt.client as mqtt
import psycopg

from myproj.collector import CollectionState, collect_telemetry, run_collector
from myproj.models import TelemetryValidationError


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
        collect_telemetry(userdata, message.topic, message.payload)
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
        run_collector(client, state)


if __name__ == "__main__":
    main()
