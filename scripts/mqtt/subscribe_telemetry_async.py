import asyncio

import aiomqtt

from myproj.collection.mqtt_validation import parse_mqtt_telemetry
from myproj.telemetry.models import TelemetryValidationError


async def main() -> None:
    async with aiomqtt.Client("127.0.0.1", port=18883) as client:
        await client.subscribe("tmrp/devices/+/telemetry", qos=1)
        print("Subscribed to topic: tmrp/devices/+/telemetry")

        async for message in client.messages:
            try:
                msg = parse_mqtt_telemetry(str(message.topic), message.payload)
            except (UnicodeDecodeError, TelemetryValidationError) as e:
                print(f"Failed to process message: {e}")
                continue
            print(
                f"Processed message: {msg}, "
                f"device_id: {msg.device_id}, "
                f"sequence_no: {msg.sequence_no}, "
                f"battery_percent: {msg.battery_percent}"
            )


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Subscription stopped by user")
