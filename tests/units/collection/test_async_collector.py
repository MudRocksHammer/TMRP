import asyncio
from collections.abc import Awaitable, Iterable
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any
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

        async def tracked_consumer(queue, conn, batch_size, flush_interval):
            try:
                consumer_started.set()
                return await original_consume(queue, conn, batch_size, flush_interval)
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


def test_consume_to_db_with_flush_interval(
    sample_message: TelemetryMessage, monkeypatch: pytest.MonkeyPatch
) -> None:
    conn = AsyncMock(spec=AsyncConnection)

    async def scenario() -> None:
        saved = asyncio.Event()

        async def fake_insert_async(conn, messages):
            assert len(messages) == 1
            assert list(messages) == [sample_message]
            saved.set()
            return 1

        save = AsyncMock(side_effect=fake_insert_async)
        monkeypatch.setattr(collector, "insert_telemetry_batch_async", save)

        queue: asyncio.Queue[TelemetryMessage | None] = asyncio.Queue()
        queue.put_nowait(sample_message)

        flush_interval = 0.01
        task = asyncio.create_task(
            collector.consume_to_db(
                queue=queue,
                conn=conn,
                batch_size=3,
                flush_interval=flush_interval,
            )
        )
        await asyncio.wait_for(saved.wait(), timeout=1)
        assert not task.done()

        await queue.put(None)
        assert await asyncio.wait_for(task, timeout=1) == 1
        await asyncio.wait_for(queue.join(), timeout=1)
        save.assert_awaited_once()

    asyncio.run(scenario())


def test_consume_to_db_not_called_with_empty_queue(
    sample_message: TelemetryMessage, monkeypatch: pytest.MonkeyPatch
) -> None:
    conn = AsyncMock(spec=AsyncConnection)

    async def scenario() -> None:
        saved = asyncio.Event()

        async def fake_insert_async(conn, messages):
            saved.set()
            return 1

        save = AsyncMock(side_effect=fake_insert_async)
        monkeypatch.setattr(collector, "insert_telemetry_batch_async", save)

        queue: asyncio.Queue[TelemetryMessage | None] = asyncio.Queue()

        task = asyncio.create_task(
            collector.consume_to_db(
                queue=queue,
                conn=conn,
                batch_size=1,
                flush_interval=0.01,
            )
        )
        await asyncio.sleep(0.1)
        assert not saved.is_set()

        await queue.put(None)
        assert await asyncio.wait_for(task, timeout=1) == 0
        await asyncio.wait_for(queue.join(), timeout=1)
        save.assert_not_awaited()

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "flush_interval",
    [0, -1, float("inf"), float("-inf"), float("nan")],
)
def test_consume_to_db_with_invalid_flush_interval(
    sample_message: TelemetryMessage,
    flush_interval: float,
) -> None:
    conn = AsyncMock(spec=AsyncConnection)

    async def scenario() -> None:
        queue: asyncio.Queue[TelemetryMessage | None] = asyncio.Queue()
        queue.put_nowait(sample_message)

        with pytest.raises(ValueError, match="flush_interval must be positive"):
            await collector.consume_to_db(
                queue=queue,
                conn=conn,
                batch_size=3,
                flush_interval=flush_interval,
            )

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "flush_interval",
    [0, -1, float("inf"), float("-inf"), float("nan")],
)
def test_run_db_pipeline_with_invalid_flush_interval(
    sample_message: TelemetryMessage,
    flush_interval: float,
) -> None:
    conn = AsyncMock(spec=AsyncConnection)

    async def scenario() -> None:
        groups = {"group1": [sample_message]}

        with pytest.raises(ValueError, match="flush_interval must be positive"):
            await collector.run_db_pipeline(
                groups=groups,
                conn=conn,
                delay=0,
                batch_size=3,
                flush_interval=flush_interval,
            )

    asyncio.run(scenario())


def test_consume_to_db_keeps_first_message_deadline(
    sample_message: TelemetryMessage, monkeypatch: pytest.MonkeyPatch
) -> None:
    conn = AsyncMock(spec=AsyncConnection)
    second = replace(sample_message, sequence_no=sample_message.sequence_no + 1)

    async def scenario() -> None:
        now = 100.0
        timeouts: list[float] = []
        saved_batches: list[list[TelemetryMessage]] = []

        async def observed_wait_for(
            awaitable: Awaitable[TelemetryMessage | None], timeout: float
        ) -> TelemetryMessage | None:
            nonlocal now
            timeouts.append(timeout)
            if len(timeouts) == 1:
                # 1件目の期限を決めた後、2件目の受信まで0.4秒進める。
                now = 100.4
            return await asyncio.wait_for(awaitable, timeout=timeout)

        # consumerが読む時計だけを差し替え、本物のイベントループは変更しない。
        monkeypatch.setattr(
            collector,
            "asyncio",
            SimpleNamespace(
                get_running_loop=lambda: SimpleNamespace(time=lambda: now),
                wait_for=observed_wait_for,
                TimeoutError=TimeoutError,
            ),
        )

        async def fake_insert(
            conn: AsyncConnection[tuple[Any, ...]],
            messages: Iterable[TelemetryMessage],
        ) -> int:
            batch = list(messages)
            saved_batches.append(batch)
            return len(batch)

        save = AsyncMock(side_effect=fake_insert)
        monkeypatch.setattr(collector, "insert_telemetry_batch_async", save)

        queue: asyncio.Queue[TelemetryMessage | None] = asyncio.Queue()
        queue.put_nowait(sample_message)
        queue.put_nowait(second)
        queue.put_nowait(None)

        inserted = await asyncio.wait_for(
            collector.consume_to_db(queue, conn, batch_size=3, flush_interval=1.0),
            timeout=1,
        )

        # 期限101.0は変わらず、2件目の受信後は残り0.6秒になる。
        assert timeouts == pytest.approx([1.0, 0.6])
        assert inserted == 2
        assert saved_batches == [[sample_message, second]]
        save.assert_awaited_once()
        await asyncio.wait_for(queue.join(), timeout=1)

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "failure",
    [RuntimeError("DB save failed"), TimeoutError("DB save timed out")],
    ids=["runtime-error", "db-timeout"],
)
def test_consume_to_db_propagates_timed_flush_failure(
    sample_message: TelemetryMessage,
    monkeypatch: pytest.MonkeyPatch,
    failure: Exception,
) -> None:
    conn = AsyncMock(spec=AsyncConnection)
    save = AsyncMock(side_effect=failure)
    monkeypatch.setattr(collector, "insert_telemetry_batch_async", save)

    async def scenario() -> None:
        queue: asyncio.Queue[TelemetryMessage | None] = asyncio.Queue()
        queue.put_nowait(sample_message)
        # Noneは送らず、件数条件にも達しないため、時間による保存を通る。
        with pytest.raises(type(failure)) as exc_info:
            await asyncio.wait_for(
                collector.consume_to_db(queue, conn, batch_size=3, flush_interval=0.01),
                timeout=1,
            )

        # テスト自身のwait_forによるTimeoutErrorとの取り違えを防ぐ。
        assert exc_info.value is failure
        save.assert_awaited_once_with(conn, [sample_message])
        await asyncio.wait_for(queue.join(), timeout=1)

    asyncio.run(scenario())
