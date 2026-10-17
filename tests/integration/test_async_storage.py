import asyncio
import os
from dataclasses import replace
from pathlib import Path

import psycopg
import pytest

from myproj.async_storage import insert_telemetry_async, insert_telemetry_batch_async
from myproj.models import TelemetryMessage


@pytest.fixture
def sample_dsn() -> str:
    dsn = os.environ.get("TMRP_TEST_DSN")
    if not dsn:
        pytest.skip("TMRP_TEST_DSN environment variable is not set")
    return dsn


@pytest.fixture
def sample_schema() -> str:
    project_root = Path(__file__).resolve().parents[2]
    schema = (project_root / "sql/001_create_telemetry.sql").read_text(encoding="utf-8")
    schema = schema.replace(
        "CREATE TABLE telemetry_messages",
        "CREATE TEMP TABLE telemetry_messages",
        1,
    )
    return schema


def test_async_storage_saves_and_skips_duplicates(
    sample_dsn: str,
    sample_message: TelemetryMessage,
    sample_schema: str,
) -> None:
    async def scenario() -> None:
        async with await psycopg.AsyncConnection.connect(
            sample_dsn,
            autocommit=True,
            options="-c timezone=UTC -c search_path=pg_temp",
        ) as conn:
            await conn.execute(sample_schema)

            assert (await insert_telemetry_async(conn, sample_message)) is True
            assert (await insert_telemetry_async(conn, sample_message)) is False

            async with conn.cursor() as cur:
                await cur.execute(
                    "SELECT device_id, sequence_no, event_time, "
                    "battery_percent, payload "
                    "FROM telemetry_messages"
                )
                row = await cur.fetchall()
                assert row is not None
                assert len(row) == 1
                assert row[0][0] == sample_message.device_id
                assert row[0][1] == sample_message.sequence_no
                assert row[0][2] == sample_message.event_time
                assert row[0][3] == sample_message.battery_percent
                assert row[0][4] == sample_message.to_dict()

    asyncio.run(scenario())


def test_async_storage_batch_inserts(
    sample_dsn: str,
    sample_message: TelemetryMessage,
    sample_schema: str,
) -> None:
    async def scenario() -> None:
        async with await psycopg.AsyncConnection.connect(
            sample_dsn,
            autocommit=True,
            options="-c timezone=UTC -c search_path=pg_temp",
        ) as conn:
            await conn.execute(sample_schema)

            second = replace(sample_message, sequence_no=sample_message.sequence_no + 1)
            messages = [sample_message, second]
            inserted_count = await insert_telemetry_batch_async(conn, messages)
            assert inserted_count == 2

            # Attempt to insert duplicates
            inserted_count = await insert_telemetry_batch_async(conn, messages)
            assert inserted_count == 0

            async with conn.cursor() as cur:
                await cur.execute(
                    "SELECT device_id, sequence_no, event_time, "
                    "battery_percent, payload "
                    "FROM telemetry_messages "
                    "ORDER BY sequence_no"
                )
                row = await cur.fetchall()
                assert row is not None
                assert len(row) == 2

                assert row[0][0] == sample_message.device_id
                assert row[0][1] == sample_message.sequence_no
                assert row[0][2] == sample_message.event_time
                assert row[0][3] == sample_message.battery_percent
                assert row[0][4] == sample_message.to_dict()

                assert row[1][0] == second.device_id
                assert row[1][1] == second.sequence_no
                assert row[1][2] == second.event_time
                assert row[1][3] == second.battery_percent
                assert row[1][4] == second.to_dict()

    asyncio.run(scenario())


def test_async_storage_batch_inserts_and_skips_duplicates(
    sample_dsn: str,
    sample_message: TelemetryMessage,
    sample_schema: str,
) -> None:
    async def scenario() -> None:
        async with await psycopg.AsyncConnection.connect(
            sample_dsn,
            autocommit=True,
            options="-c timezone=UTC -c search_path=pg_temp",
        ) as conn:
            await conn.execute(sample_schema)

            second = replace(sample_message, sequence_no=sample_message.sequence_no + 1)
            messages = [
                sample_message,
                second,
                sample_message,
            ]
            inserted_count = await insert_telemetry_batch_async(conn, messages)
            assert inserted_count == 2

            # Attempt to insert duplicates
            inserted_count = await insert_telemetry_batch_async(conn, messages)
            assert inserted_count == 0

            async with conn.cursor() as cur:
                await cur.execute(
                    "SELECT device_id, sequence_no, event_time, "
                    "battery_percent, payload "
                    "FROM telemetry_messages "
                    "ORDER BY sequence_no"
                )
                row = await cur.fetchall()
                assert row is not None
                assert len(row) == 2

                assert row[0][0] == sample_message.device_id
                assert row[0][1] == sample_message.sequence_no
                assert row[0][2] == sample_message.event_time
                assert row[0][3] == sample_message.battery_percent
                assert row[0][4] == sample_message.to_dict()

                assert row[1][0] == second.device_id
                assert row[1][1] == second.sequence_no
                assert row[1][2] == second.event_time
                assert row[1][3] == second.battery_percent
                assert row[1][4] == second.to_dict()

    asyncio.run(scenario())


def test_async_storage_batch_inserts_emptry_list(
    sample_dsn: str,
    sample_schema: str,
) -> None:
    async def scenario() -> None:
        async with await psycopg.AsyncConnection.connect(
            sample_dsn,
            autocommit=True,
            options="-c timezone=UTC -c search_path=pg_temp",
        ) as conn:
            await conn.execute(sample_schema)

            messages: list[TelemetryMessage] = []
            inserted_count = await insert_telemetry_batch_async(conn, messages)
            assert inserted_count == 0

            async with conn.cursor() as cur:
                await cur.execute(
                    "SELECT device_id, sequence_no, event_time, "
                    "battery_percent, payload "
                    "FROM telemetry_messages"
                )
                row = await cur.fetchall()
                assert row is not None
                assert len(row) == 0

    asyncio.run(scenario())


def test_async_storage_batch_failed_inserts(
    sample_dsn: str,
    sample_schema: str,
    sample_message: TelemetryMessage,
) -> None:
    async def scenario() -> None:
        async with await psycopg.AsyncConnection.connect(
            sample_dsn,
            autocommit=True,
            options="-c timezone=UTC -c search_path=pg_temp",
        ) as conn:
            await conn.execute(sample_schema)
            await conn.execute(
                """
                ALTER TABLE pg_temp.telemetry_messages
                ADD CONSTRAINT test_async_battery_limit
                CHECK (battery_percent < 90)
                """
            )

            bad_message = replace(
                sample_message,
                sequence_no=sample_message.sequence_no + 1,
                battery_percent=99,
            )

            with pytest.raises(psycopg.errors.CheckViolation):
                await insert_telemetry_batch_async(conn, [sample_message, bad_message])

            async with conn.cursor() as cur:
                await cur.execute(
                    "SELECT device_id, sequence_no, event_time, "
                    "battery_percent, payload "
                    "FROM telemetry_messages"
                )
                row = await cur.fetchall()
                assert row is not None
                assert len(row) == 0

    asyncio.run(scenario())
