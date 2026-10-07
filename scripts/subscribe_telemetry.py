import sys

import paho.mqtt.client as mqtt

from myproj.models import TelemetryValidationError
from myproj.mqtt_validation import parse_mqtt_telemetry


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
        device_id = telemetry_message.device_id
        print(f"解析成功: device_id={device_id}, telemetry_message={telemetry_message}")
    except (UnicodeDecodeError, TelemetryValidationError) as e:
        print(f"解析失敗: {e}", file=sys.stderr)
        return


def main() -> None:
    client = mqtt.Client(callback_api_version=mqtt.CallbackAPIVersion.VERSION2)
    client.on_connect = on_connect
    client.on_message = on_message

    client.connect("127.0.0.1", 18883, keepalive=60)
    try:
        client.loop_forever()
    except KeyboardInterrupt:
        print("終了します")
    finally:
        client.disconnect()


if __name__ == "__main__":
    main()
