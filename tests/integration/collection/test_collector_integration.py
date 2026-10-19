from dataclasses import replace
from typing import Any

import psycopg
import pytest
from psycopg import Connection

import myproj.collection.collector as collector
from myproj.telemetry.models import TelemetryMessage


def test_insert_telemetry_saves_messages(
    db_conn: Connection[tuple[Any, ...]], sample_message: TelemetryMessage
) -> None:
    messages = [
        replace(sample_message, sequence_no=sample_message.sequence_no + offset)
        for offset in range(3)
    ]
    state = collector.CollectionState(conn=db_conn)
    for count, message in enumerate(messages, start=1):
        collector.collect_telemetry(
            state,
            f"tmrp/devices/{message.device_id}/telemetry",
            message.to_json().encode("utf-8"),
        )

        if count < 3:
            assert db_conn.execute(
                "SELECT COUNT(*) FROM pg_temp.telemetry_messages"
            ).fetchone() == (0,)

    assert state.pending == []

    assert db_conn.execute(
        "SELECT COUNT(*) FROM pg_temp.telemetry_messages"
    ).fetchone() == (3,)

    rows = db_conn.execute(
        """
        SELECT sequence_no, payload
        FROM pg_temp.telemetry_messages
        ORDER BY sequence_no
        """
    ).fetchall()

    assert rows == [(message.sequence_no, message.to_dict()) for message in messages]


def test_insert_telemetry_duplicates(
    db_conn: Connection[tuple[Any, ...]], sample_message: TelemetryMessage
) -> None:
    messages = [
        sample_message,
        sample_message,
        sample_message,
    ]
    state = collector.CollectionState(conn=db_conn)
    for message in messages:
        collector.collect_telemetry(
            state,
            f"tmrp/devices/{sample_message.device_id}/telemetry",
            message.to_json().encode("utf-8"),
        )

    assert db_conn.execute(
        "SELECT COUNT(*) FROM pg_temp.telemetry_messages"
    ).fetchone() == (1,)

    assert state.pending == []


def test_insert_telemetry_failed_third(
    db_conn: Connection[tuple[Any, ...]], sample_message: TelemetryMessage
) -> None:

    db_conn.execute(
        """
        ALTER TABLE pg_temp.telemetry_messages
        ADD CONSTRAINT test_battery_limit
        CHECK (battery_percent < 90)
        """
    )

    messages = [
        replace(sample_message, battery_percent=82.5),
        replace(
            sample_message,
            sequence_no=sample_message.sequence_no + 1,
            battery_percent=82.5,
        ),
        replace(
            sample_message,
            sequence_no=sample_message.sequence_no + 2,
            battery_percent=99.0,
        ),
    ]
    state = collector.CollectionState(conn=db_conn)

    with pytest.raises(psycopg.errors.CheckViolation):
        for i, message in enumerate(messages):
            collector.collect_telemetry(
                state,
                f"tmrp/devices/{sample_message.device_id}/telemetry",
                message.to_json().encode("utf-8"),
            )

    assert db_conn.execute(
        "SELECT COUNT(*) FROM pg_temp.telemetry_messages"
    ).fetchone() == (0,)

    assert state.pending == messages
