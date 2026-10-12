from dataclasses import replace
from typing import Any

import pytest
from psycopg import Connection

from myproj.models import TelemetryMessage
from myproj.storage import insert_telemetry, insert_telemetry_batch


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
