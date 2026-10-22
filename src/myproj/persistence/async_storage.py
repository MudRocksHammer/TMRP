from collections.abc import Iterable
from typing import Any

from psycopg import AsyncConnection
from psycopg.types.json import Jsonb

from myproj.telemetry.models import TelemetryMessage


async def insert_telemetry_async(
    conn: AsyncConnection[tuple[Any, ...]],
    message: TelemetryMessage,
) -> bool:
    sql = """
                INSERT INTO telemetry_messages (
                    device_id, sequence_no, event_time, battery_percent, payload
                )
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT ON CONSTRAINT telemetry_messages_event_key
                DO NOTHING
                RETURNING id
            """
    values = (
        message.device_id,
        message.sequence_no,
        message.event_time,
        message.battery_percent,
        Jsonb(message.to_dict()),
    )

    async with conn.cursor() as cur:
        await cur.execute(sql, values)
        row = await cur.fetchone()

    return row is not None


async def insert_telemetry_batch_async(
    conn: AsyncConnection[tuple[Any, ...]],
    messages: Iterable[TelemetryMessage],
) -> int:
    inserted_count = 0
    async with conn.transaction():
        for message in messages:
            inserted = await insert_telemetry_async(conn, message)
            if inserted:
                inserted_count += 1

    return inserted_count


async def insert_telemetry_batch_async_multi(
    conn: AsyncConnection[tuple[Any, ...]],
    messages: Iterable[TelemetryMessage],
) -> int:
    items = list(messages)
    if not items:
        return 0

    placeholders = ", ".join(["(%s, %s, %s, %s, %s)"] * len(items))

    sql = f"""
        INSERT INTO telemetry_messages (
            device_id, sequence_no, event_time, battery_percent, payload
        )
        VALUES {placeholders}
        ON CONFLICT ON CONSTRAINT telemetry_messages_event_key
        DO NOTHING
        RETURNING id
    """
    values = [
        (
            message.device_id,
            message.sequence_no,
            message.event_time,
            message.battery_percent,
            Jsonb(message.to_dict()),
        )
        for message in items
    ]
    async with conn.transaction():
        async with conn.cursor() as cur:
            await cur.execute(sql, [value for tup in values for value in tup])
            rows = await cur.fetchall()
    return len(rows)
