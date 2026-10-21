import asyncio
from collections.abc import AsyncIterator
from dataclasses import replace
from unittest import result

import psycopg
from aiomqtt import Message

from myproj.collection.async_mqtt import run_mqtt_db_pipeline
from myproj.telemetry.models import TelemetryMessage


def mqtt_message(topic: str, payload: bytes) -> Message:
    return Message(
        topic=topic,
        payload=payload,
        qos=1,
        retain=False,
        mid=1,
        properties=None,
    )


async def fake_messages(inputs: list[Message]) -> AsyncIterator[Message]:
    for message in inputs:
        yield message


def test_mqtt_pipeline_saves_and_ignores_duplicates(
    sample_dsn: str,
    sample_schema: str,
    sample_message: TelemetryMessage,
) -> None:
    samples = [
        sample_message,
        replace(sample_message, device_id="robot-002", sequence_no=1002),
        replace(sample_message, device_id="robot-002", sequence_no=1003),
        replace(sample_message, device_id="robot-002", sequence_no=1004),
        replace(sample_message, device_id="robot-002", sequence_no=1005),
    ]

    inputs = [
        mqtt_message(
            f"tmrp/devices/{sample.device_id}/telemetry",
            sample.to_json().encode("utf-8"),
        )
        for sample in samples
    ]

    inputs.insert(
        2,
        mqtt_message("tmrp/devices/robot-001/telemetry", b"{invalid"),
    )

    async def scenario():
        async with await psycopg.AsyncConnection.connect(
            sample_dsn,
            autocommit=True,
            options="-c timezone=utc -c search_path=pg_temp",
        ) as conn:
            await conn.execute(sample_schema)

            inserted = await asyncio.wait_for(
                run_mqtt_db_pipeline(fake_messages(inputs), conn),
                timeout=5,
            )

            assert inserted == 5

            result = await conn.execute(
                "SELECT device_id, sequence_no, event_time, battery_percent, payload "
                "FROM telemetry_messages "
                "ORDER BY sequence_no"
            )

            rows = await result.fetchall()
            assert len(rows) == 5
            for row, sample in zip(rows, samples):
                assert row[0] == sample.device_id
                assert row[1] == sample.sequence_no
                assert row[2] == sample.event_time
                assert row[3] == sample.battery_percent
                assert row[4] == sample.to_dict()

            inserted_again = await asyncio.wait_for(
                run_mqtt_db_pipeline(fake_messages(inputs), conn),
                timeout=5,
            )
            assert inserted_again == 0

            result = await conn.execute(
                "SELECT device_id, sequence_no, event_time, battery_percent, payload "
                "FROM telemetry_messages ORDER BY sequence_no"
            )
            assert await result.fetchall() == rows

    asyncio.run(scenario())
