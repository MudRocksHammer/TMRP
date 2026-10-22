from dataclasses import replace
from typing import Any

import psycopg
import pytest
from psycopg import Connection

from myproj.persistence.storage import (
    insert_telemetry,
    insert_telemetry_batch,
    insert_telemetry_batch_multi,
)
from myproj.telemetry.models import TelemetryMessage


def test_insert_telemetry_saves_message(
    db_conn: Connection[tuple[Any, ...]], sample_message: TelemetryMessage
) -> None:
    assert insert_telemetry(db_conn, sample_message) is True
    row = db_conn.execute(
        """
        SELECT device_id, sequence_no, event_time, battery_percent, payload
        FROM telemetry_messages
    """
    ).fetchone()
    assert row is not None
    assert row[0] == sample_message.device_id
    assert row[1] == sample_message.sequence_no
    assert row[2] == sample_message.event_time
    assert row[3] == sample_message.battery_percent
    assert row[4] == sample_message.to_dict()


def test_insert_telemetry_skips_duplicate(
    db_conn: Connection[tuple[Any, ...]], sample_message: TelemetryMessage
) -> None:
    assert insert_telemetry(db_conn, sample_message) is True
    assert insert_telemetry(db_conn, sample_message) is False
    assert db_conn.execute("SELECT COUNT(*) FROM telemetry_messages").fetchone() == (1,)


def test_insert_telemetry_can_be_rolled_back(
    db_conn: Connection[tuple[Any, ...]], sample_message: TelemetryMessage
) -> None:
    with pytest.raises(RuntimeError, match="^rollback test$"):
        with db_conn.transaction():
            assert insert_telemetry(db_conn, sample_message) is True
            raise RuntimeError("rollback test")

    result = db_conn.execute("SELECT * FROM telemetry_messages").fetchall()
    assert len(result) == 0


def test_insert_telemetry_batch_two_different_messages(
    db_conn: Connection[tuple[Any, ...]], sample_message: TelemetryMessage
) -> None:
    second_message = replace(
        sample_message,
        sequence_no=sample_message.sequence_no + 1,
    )
    inserted_count = insert_telemetry_batch(db_conn, [sample_message, second_message])
    assert inserted_count == 2
    result = db_conn.execute(
        "SELECT * FROM telemetry_messages ORDER BY sequence_no"
    ).fetchall()
    assert len(result) == 2
    assert result[0][2] == sample_message.sequence_no
    assert result[1][2] == sample_message.sequence_no + 1


def test_insert_telemetry_batch_skips_duplicates(
    db_conn: Connection[tuple[Any, ...]], sample_message: TelemetryMessage
) -> None:
    second_message = replace(
        sample_message,
        sequence_no=sample_message.sequence_no + 1,
    )
    inserted_count = insert_telemetry_batch(
        db_conn, [sample_message, second_message, sample_message]
    )
    assert inserted_count == 2
    result = db_conn.execute(
        "SELECT * FROM telemetry_messages ORDER BY sequence_no"
    ).fetchall()
    assert len(result) == 2
    assert result[0][2] == sample_message.sequence_no
    assert result[1][2] == sample_message.sequence_no + 1


def test_insert_telemetry_batch_null_list(db_conn: Connection[tuple[Any, ...]]) -> None:
    inserted_count = insert_telemetry_batch(db_conn, [])
    assert inserted_count == 0
    result = db_conn.execute(
        "SELECT * FROM telemetry_messages ORDER BY sequence_no"
    ).fetchall()
    assert len(result) == 0


def test_insert_telemetry_batch_exception_during_execution(
    db_conn: Connection[tuple[Any, ...]], sample_message: TelemetryMessage
) -> None:
    def failing_messages():
        yield sample_message
        raise RuntimeError("batch test failure")

    with pytest.raises(RuntimeError, match="^batch test failure$"):
        insert_telemetry_batch(db_conn, failing_messages())

    result = db_conn.execute(
        "SELECT * FROM telemetry_messages ORDER BY sequence_no"
    ).fetchall()
    assert len(result) == 0


def test_insert_telemetry_batch_multi(
    db_conn: Connection[tuple[Any, ...]], sample_message: TelemetryMessage
) -> None:
    second_message = replace(
        sample_message,
        sequence_no=sample_message.sequence_no + 1,
    )
    messages = [
        sample_message,
        second_message,
    ]
    inserted_count = insert_telemetry_batch_multi(db_conn, messages)
    assert inserted_count == 2
    result = db_conn.execute(
        "SELECT device_id, sequence_no,  event_time, battery_percent, payload"
        " FROM telemetry_messages ORDER BY sequence_no"
    ).fetchall()
    assert len(result) == 2
    assert result[0][1] == sample_message.sequence_no
    assert result[1][1] == sample_message.sequence_no + 1
    assert result[0][0] == sample_message.device_id
    assert result[1][0] == second_message.device_id
    assert result[0][2] == sample_message.event_time
    assert result[1][2] == second_message.event_time
    assert result[0][3] == sample_message.battery_percent
    assert result[1][3] == second_message.battery_percent
    assert result[0][4] == sample_message.to_dict()
    assert result[1][4] == second_message.to_dict()


def test_insert_telemetry_batch_multi_skips_duplicates(
    db_conn: Connection[tuple[Any, ...]], sample_message: TelemetryMessage
) -> None:
    second_message = replace(
        sample_message,
        sequence_no=sample_message.sequence_no + 1,
    )
    inserted_count = insert_telemetry_batch_multi(
        db_conn, [sample_message, second_message, sample_message]
    )
    assert inserted_count == 2
    result = db_conn.execute(
        "SELECT device_id, sequence_no,  event_time, battery_percent, payload"
        " FROM telemetry_messages ORDER BY sequence_no"
    ).fetchall()
    assert len(result) == 2
    assert result[0][1] == sample_message.sequence_no
    assert result[1][1] == sample_message.sequence_no + 1

    inserted_count = insert_telemetry_batch_multi(
        db_conn, [sample_message, second_message, sample_message]
    )
    assert inserted_count == 0
    row_after = db_conn.execute(
        "SELECT device_id, sequence_no,  event_time, battery_percent, payload"
        " FROM telemetry_messages ORDER BY sequence_no"
    ).fetchall()
    assert len(row_after) == 2
    assert row_after == result


def test_insert_telemetry_batch_multi_empty_list(
    db_conn: Connection[tuple[Any, ...]],
) -> None:
    inserted_count = insert_telemetry_batch_multi(db_conn, [])
    assert inserted_count == 0
    result = db_conn.execute(
        "SELECT * FROM telemetry_messages ORDER BY sequence_no"
    ).fetchall()
    assert len(result) == 0


def test_insert_telemetry_batch_multi_with_constraint_violation(
    db_conn: Connection[tuple[Any, ...]], sample_message: TelemetryMessage
) -> None:
    db_conn.execute(
        "ALTER TABLE pg_temp.telemetry_messages "
        "ADD CONSTRAINT test_multi_battery_limit "
        "CHECK (battery_percent < 90)"
    )
    violating_message = replace(
        sample_message, sequence_no=sample_message.sequence_no + 1, battery_percent=95
    )
    with pytest.raises(psycopg.errors.CheckViolation):
        insert_telemetry_batch_multi(db_conn, [sample_message, violating_message])

    result = db_conn.execute("SELECT COUNT(*) FROM telemetry_messages").fetchone()
    assert result == (0,)
