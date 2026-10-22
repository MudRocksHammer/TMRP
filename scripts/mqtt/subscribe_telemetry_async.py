import asyncio

import aiomqtt
import psycopg

from myproj.collection.async_mqtt import run_mqtt_db_pipeline, take_messages


async def main() -> None:
    async with await psycopg.AsyncConnection.connect(
        "host=/var/run/postgresql port=5432 dbname=tmrp_dev user=shou",
        autocommit=True,
        options="-c timezone=UTC",
    ) as conn:
        async with aiomqtt.Client("127.0.0.1", port=18883) as client:
            await client.subscribe("tmrp/devices/+/telemetry", qos=1)
            print("Subscribed to topic: tmrp/devices/+/telemetry")

            inserted = await run_mqtt_db_pipeline(
                take_messages(client.messages, limit=10),
                conn,
                batch_size=3,
                flush_interval=1.0,
            )

            print(f"Inserted {inserted} messages into the database")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Subscription stopped by user")
