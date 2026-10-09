from collections.abc import Iterable
from typing import Any

from psycopg import Connection
from psycopg.types.json import Jsonb

from myproj.models import TelemetryMessage


def insert_telemetry(
    conn: Connection[tuple[Any, ...]],
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

    row = conn.execute(sql, values).fetchone()
    return row is not None


def insert_telemetry_batch(
    conn: Connection[tuple[Any, ...]],
    messages: Iterable[TelemetryMessage],
) -> int:
    inserted_count = 0
    with conn.transaction():
        for message in messages:
            row = insert_telemetry(conn, message)
            if row:
                inserted_count += 1
    return inserted_count
