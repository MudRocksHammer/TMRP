import time
from datetime import datetime, timezone

from paho.mqtt import publish

from myproj.models import MessageType, TelemetryMessage


def main() -> None:
    battery_values: dict[str, list[float | None]] = {
        "robot-001": [100.0, 98.0, 96.0, 92.0, 90.0],
        "robot-002": [80.0, 78.0, 76.0, 74.0, 70.0],
    }

    for index in range(1, 6):
        messages = []
        for device_id, value in battery_values.items():
            message = TelemetryMessage(
                schema_version="1.0",
                device_id=device_id,
                sequence_no=index,
                event_time=datetime.now(timezone.utc),
                message_type=MessageType.TELEMETRY,
                battery_percent=value[index - 1],
            )

            messages.append(
                {
                    "topic": f"tmrp/devices/{device_id}/telemetry",
                    "payload": message.to_json(),
                    "qos": 1,
                    "retain": False,
                }
            )
        publish.multiple(messages, hostname="127.0.0.1", port=18883)

        print(f"連番{index}: {len(messages)}件をBrokerへ送信しました")

        if index < 5:
            time.sleep(1)


if __name__ == "__main__":
    main()
