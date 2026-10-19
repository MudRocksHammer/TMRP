import asyncio
from dataclasses import replace
from pathlib import Path

import psycopg
import pytest

import myproj.async_collector as collector
from myproj.models import TelemetryMessage
from myproj.stream import iter_telemetry


def test_insert_telemetry_saves_messages_async(
    sample_dsn, sample_schema, sample_message
) -> None:
    insert_messages = [
        sample_message,
        replace(sample_message, sequence_no=sample_message.sequence_no + 1),
        replace(sample_message, sequence_no=sample_message.sequence_no + 2),
        replace(sample_message, sequence_no=sample_message.sequence_no + 3),
        replace(sample_message, sequence_no=sample_message.sequence_no + 4),
    ]

    async def scenario() -> None:
        async with await psycopg.AsyncConnection.connect(
            sample_dsn,
            autocommit=True,
            options="-c timezone=UTC -c search_path=pg_temp",
        ) as conn:
            await conn.execute(sample_schema)

            queue: asyncio.Queue[TelemetryMessage | None] = asyncio.Queue()
            for message in insert_messages:
                await queue.put(message)
            await queue.put(None)

            inserted = await asyncio.wait_for(
                collector.consume_to_db(queue, conn, 3),
                timeout=1,
            )

            assert inserted == len(insert_messages)

            await asyncio.wait_for(queue.join(), timeout=1)

            async with conn.cursor() as cur:
                await cur.execute(
                    "SELECT device_id, sequence_no, event_time, "
                    "battery_percent, payload FROM telemetry_messages "
                    "ORDER BY sequence_no"
                )
                rows = await cur.fetchall()

            assert len(rows) == len(insert_messages)
            for i, row in enumerate(rows):
                assert row[0] == insert_messages[i].device_id
                assert row[1] == insert_messages[i].sequence_no
                assert row[2] == insert_messages[i].event_time
                assert row[3] == insert_messages[i].battery_percent
                assert row[4] == insert_messages[i].to_dict()

            for message in insert_messages:
                await queue.put(message)
            await queue.put(None)

            inserted = await asyncio.wait_for(
                collector.consume_to_db(queue, conn, 3),
                timeout=1,
            )

            await asyncio.wait_for(queue.join(), timeout=1)

            assert inserted == 0

            async with conn.cursor() as cur:
                await cur.execute(
                    "SELECT device_id, sequence_no, event_time, "
                    "battery_percent, payload FROM telemetry_messages "
                    "ORDER BY sequence_no"
                )
                assert await cur.fetchall() == rows

    asyncio.run(scenario())


def test_async_collector_batch_failed_inserts(
    sample_dsn: str, sample_schema: str, sample_message: TelemetryMessage
) -> None:
    normal_messages = [
        sample_message,
        replace(sample_message, sequence_no=sample_message.sequence_no + 1),
        replace(sample_message, sequence_no=sample_message.sequence_no + 2),
    ]

    abnormal_messages = [
        replace(sample_message, sequence_no=sample_message.sequence_no + 3),
        replace(
            sample_message,
            sequence_no=sample_message.sequence_no + 4,
            battery_percent=95,
        ),
    ]

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

            queue: asyncio.Queue[TelemetryMessage | None] = asyncio.Queue()
            for message in normal_messages:
                await queue.put(message)

            for message in abnormal_messages:
                await queue.put(message)
            await queue.put(None)

            with pytest.raises(psycopg.errors.CheckViolation):
                await asyncio.wait_for(
                    collector.consume_to_db(queue, conn, 3),
                    timeout=5,
                )

            await asyncio.wait_for(queue.join(), timeout=1)

            async with conn.cursor() as cur:
                await cur.execute(
                    "SELECT sequence_no FROM telemetry_messages ORDER BY sequence_no"
                )
                rows = await cur.fetchall()

                assert rows == [(message.sequence_no,) for message in normal_messages]

    asyncio.run(scenario())


@pytest.fixture
def battery_alerts() -> list[TelemetryMessage]:
    project_root = Path(__file__).resolve().parents[2]

    input_file = project_root / "examples/telemetry/battery_alerts.jsonl"
    with open(input_file, "r", encoding="utf-8") as f:
        return list(iter_telemetry(f))


def test_async_collector_run_db_pipeline(
    sample_dsn: str,
    sample_schema: str,
    battery_alerts: list[TelemetryMessage],
) -> None:
    async def scenario() -> None:
        async with await psycopg.AsyncConnection.connect(
            sample_dsn,
            autocommit=True,
            options="-c timezone=UTC -c search_path=pg_temp",
        ) as conn:
            await conn.execute(sample_schema)

            groups: dict[str, list[TelemetryMessage]] = {}
            for message in battery_alerts:
                groups.setdefault(message.device_id, []).append(message)

            inserted = await asyncio.wait_for(
                collector.run_db_pipeline(groups, conn, delay=0, batch_size=3),
                timeout=5,
            )

            assert inserted == len(battery_alerts)

            async with conn.cursor() as cur:
                await cur.execute(
                    "SELECT device_id, sequence_no, event_time, "
                    "battery_percent, payload FROM telemetry_messages "
                    "ORDER BY device_id, sequence_no"
                )
                rows = await cur.fetchall()

                expected = sorted(
                    battery_alerts, key=lambda m: (m.device_id, m.sequence_no)
                )

                assert rows == [
                    (
                        message.device_id,
                        message.sequence_no,
                        message.event_time,
                        message.battery_percent,
                        message.to_dict(),
                    )
                    for message in expected
                ]

            inserted = await asyncio.wait_for(
                collector.run_db_pipeline(groups, conn, delay=0, batch_size=3),
                timeout=5,
            )

            assert inserted == 0

            async with conn.cursor() as cur:
                await cur.execute(
                    "SELECT device_id, sequence_no, event_time, "
                    "battery_percent, payload FROM telemetry_messages "
                    "ORDER BY device_id, sequence_no"
                )
                rows = await cur.fetchall()

                expected = sorted(
                    battery_alerts, key=lambda m: (m.device_id, m.sequence_no)
                )

                assert rows == [
                    (
                        message.device_id,
                        message.sequence_no,
                        message.event_time,
                        message.battery_percent,
                        message.to_dict(),
                    )
                    for message in expected
                ]

    asyncio.run(scenario())


@pytest.mark.parametrize("battery_alerts", [{}, {"robot-001": []}])
def test_run_db_pipeline_with_empty_groups(
    battery_alerts, sample_schema, sample_dsn
) -> None:
    async def scenario():
        async with await psycopg.AsyncConnection.connect(
            sample_dsn,
            autocommit=True,
            options="-c timezone=UTC -c search_path=pg_temp",
        ) as conn:
            await conn.execute(sample_schema)

            groups: dict[str, list[TelemetryMessage]] = battery_alerts

            inserted = await asyncio.wait_for(
                collector.run_db_pipeline(groups, conn, delay=0, batch_size=3),
                timeout=5,
            )

            assert inserted == 0

            async with conn.cursor() as cur:
                await cur.execute(
                    "SELECT device_id, sequence_no, event_time, "
                    "battery_percent, payload FROM telemetry_messages "
                    "ORDER BY device_id, sequence_no"
                )
                rows = await cur.fetchall()

                expected = []

                assert rows == expected

    asyncio.run(scenario())
