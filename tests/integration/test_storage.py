import os
from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path
from typing import Any

import psycopg
import pytest
from psycopg import Connection

from myproj.models import TelemetryMessage
from myproj.storage import insert_telemetry, insert_telemetry_batch

PROJECT_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def db_conn() -> Iterator[Connection[tuple[Any, ...]]]:
    dsn = os.environ.get("TMRP_TEST_DSN")
    if not dsn:
        pytest.skip("TMRP_TEST_DSN environment variable is not set")

    schema = (PROJECT_ROOT / "sql/001_create_telemetry.sql").read_text(encoding="utf-8")

    schema = schema.replace(
        "CREATE TABLE telemetry_messages", "CREATE TEMP TABLE telemetry_messages", 1
    )

    with psycopg.connect(
        dsn,
        autocommit=True,
        options="-c timezone=UTC -c search_path=pg_temp",
    ) as conn:
        conn.execute(schema)
        yield conn


@pytest.fixture
def sample_message() -> TelemetryMessage:
    text = (PROJECT_ROOT / "examples/telemetry/valid.json").read_text(encoding="utf-8")
    return TelemetryMessage.from_json(text)


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
