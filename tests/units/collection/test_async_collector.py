import asyncio
from dataclasses import replace
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from psycopg import AsyncConnection

import myproj.collection.async_collector as collector
from myproj.telemetry.models import TelemetryMessage


@pytest.fixture
def sample_message() -> TelemetryMessage:
    project_root = Path(__file__).resolve().parents[3]
    text = (project_root / "examples/telemetry/valid.json").read_text(encoding="utf-8")
    return TelemetryMessage.from_json(text)


def test_async_collector(
    sample_message: TelemetryMessage, monkeypatch: pytest.MonkeyPatch
) -> None:
    conn = AsyncMock(spec=AsyncConnection)

    expected = [
        sample_message,
        replace(sample_message, sequence_no=sample_message.sequence_no + 1),
        replace(sample_message, sequence_no=sample_message.sequence_no + 2),
        replace(sample_message, sequence_no=sample_message.sequence_no + 3),
        replace(sample_message, sequence_no=sample_message.sequence_no + 4),
    ]

    save_messages: list[TelemetryMessage] = []
    saved_batches: list[list[TelemetryMessage]] = []

    async def fake_insert_async(conn, messages):
        saved_batches.append(list(messages))
        save_messages.extend(messages)
        return len(messages)

    save = AsyncMock(side_effect=fake_insert_async)
    monkeypatch.setattr(collector, "insert_telemetry_batch_async", save)

    async def scenario() -> None:
        queue: asyncio.Queue[TelemetryMessage | None] = asyncio.Queue()

        for message in expected:
            queue.put_nowait(message)
        queue.put_nowait(None)

        inserted = await asyncio.wait_for(
            collector.consume_to_db(queue, conn, 3), timeout=1
        )

        assert inserted == 5
        assert save_messages == expected
        save.assert_called()
        assert save.await_count == 2
        assert saved_batches == [
            expected[:3],
            expected[3:],
        ]

        await asyncio.wait_for(queue.join(), timeout=1)

    asyncio.run(scenario())


def test_consume_to_db_partial_insert(
    sample_message: TelemetryMessage, monkeypatch: pytest.MonkeyPatch
) -> None:
    conn = AsyncMock(spec=AsyncConnection)

    expected_1 = [
        sample_message,
        replace(sample_message, sequence_no=sample_message.sequence_no + 1),
        sample_message,
    ]

    expected_2 = [
        replace(sample_message, sequence_no=sample_message.sequence_no + 2),
        replace(sample_message, sequence_no=sample_message.sequence_no + 2),
    ]

    save = AsyncMock(side_effect=[2, 1])
    monkeypatch.setattr(collector, "insert_telemetry_batch_async", save)

    async def scenario() -> None:
        queue: asyncio.Queue[TelemetryMessage | None] = asyncio.Queue()

        for message in expected_1 + expected_2:
            queue.put_nowait(message)
        queue.put_nowait(None)

        inserted = await asyncio.wait_for(
            collector.consume_to_db(queue, conn, 3), timeout=1
        )

        assert inserted == 3
        save.assert_called()
        assert save.await_count == 2

        await asyncio.wait_for(queue.join(), timeout=1)

    asyncio.run(scenario())


def test_consume_to_db_empty_queue(
    sample_message: TelemetryMessage, monkeypatch: pytest.MonkeyPatch
) -> None:
    conn = AsyncMock(spec=AsyncConnection)

    save = AsyncMock(side_effect=[0])
    monkeypatch.setattr(collector, "insert_telemetry_batch_async", save)

    async def scenario() -> None:
        queue: asyncio.Queue[TelemetryMessage | None] = asyncio.Queue()

        queue.put_nowait(None)

        inserted = await asyncio.wait_for(
            collector.consume_to_db(queue, conn, 3), timeout=1
        )

        assert inserted == 0
        save.assert_not_called()
        assert save.await_count == 0

        await asyncio.wait_for(queue.join(), timeout=1)

    asyncio.run(scenario())


def test_consume_to_db_invalid_batch_size(
    sample_message: TelemetryMessage, monkeypatch: pytest.MonkeyPatch
) -> None:
    conn = AsyncMock(spec=AsyncConnection)

    async def scenario() -> None:
        queue: asyncio.Queue[TelemetryMessage | None] = asyncio.Queue()
        queue.put_nowait(sample_message)
        queue.put_nowait(None)

        with pytest.raises(ValueError):
            await asyncio.wait_for(collector.consume_to_db(queue, conn, 0), timeout=1)

        with pytest.raises(ValueError):
            await asyncio.wait_for(collector.consume_to_db(queue, conn, -1), timeout=1)

    asyncio.run(scenario())


def test_consume_to_db_save_raises(
    sample_message: TelemetryMessage, monkeypatch: pytest.MonkeyPatch
) -> None:
    conn = AsyncMock(spec=AsyncConnection)

    save = AsyncMock(side_effect=RuntimeError("insert failed"))
    monkeypatch.setattr(collector, "insert_telemetry_batch_async", save)

    async def scenario() -> None:
        queue: asyncio.Queue[TelemetryMessage | None] = asyncio.Queue()
        queue.put_nowait(sample_message)
        queue.put_nowait(None)

        with pytest.raises(RuntimeError, match="insert failed"):
            await asyncio.wait_for(collector.consume_to_db(queue, conn, 3), timeout=1)

        await asyncio.wait_for(queue.join(), timeout=1)

    asyncio.run(scenario())


def test_db_pipeline_cancels_producer_when_save_fails(
    sample_message: TelemetryMessage, monkeypatch: pytest.MonkeyPatch
) -> None:
    conn = AsyncMock(spec=AsyncConnection)

    failure = RuntimeError("insert failed")
    save = AsyncMock(side_effect=failure)
    monkeypatch.setattr(collector, "insert_telemetry_batch_async", save)

    async def scenario() -> None:
        never_finish = asyncio.Event()
        producer_finished = asyncio.Event()

        async def blocked_producer(messages, queue, delay):
            try:
                queue.put_nowait(messages[0])
                await never_finish.wait()
            finally:
                producer_finished.set()

        monkeypatch.setattr(collector, "produce", blocked_producer)

        with pytest.raises(ExceptionGroup) as exc_info:
            await asyncio.wait_for(
                collector.run_db_pipeline(
                    {"robot-001": [sample_message]},
                    conn,
                    batch_size=1,
                ),
                timeout=1,
            )

        assert exc_info.value.exceptions == (failure,)
        assert producer_finished.is_set()
        save.assert_awaited_once()

    asyncio.run(scenario())


def test_db_pipeline_cancellation_stops_all_tasks(
    sample_message: TelemetryMessage, monkeypatch: pytest.MonkeyPatch
) -> None:
    conn = AsyncMock(spec=AsyncConnection)

    async def scenario() -> None:
        never_finish = asyncio.Event()
        producer_finished = asyncio.Event()
        consumer_finished = asyncio.Event()

        producer_started = asyncio.Event()
        consumer_started = asyncio.Event()

        original_consume = collector.consume_to_db

        async def blocked_producer(messages, queue, delay):
            try:
                producer_started.set()
                await never_finish.wait()
            finally:
                producer_finished.set()

        async def tracked_consumer(queue, conn, batch_size):
            try:
                consumer_started.set()
                return await original_consume(queue, conn, batch_size)
            finally:
                consumer_finished.set()

        monkeypatch.setattr(collector, "produce", blocked_producer)
        monkeypatch.setattr(collector, "consume_to_db", tracked_consumer)

        pipeline_task = asyncio.create_task(
            collector.run_db_pipeline(
                {"robot-001": [sample_message]},
                conn,
                batch_size=1,
            )
        )
        await asyncio.wait_for(producer_started.wait(), timeout=1)
        await asyncio.wait_for(consumer_started.wait(), timeout=1)

        pipeline_task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(pipeline_task, timeout=1)

        assert pipeline_task.cancelled()
        assert producer_finished.is_set()
        assert consumer_finished.is_set()

    asyncio.run(scenario())
