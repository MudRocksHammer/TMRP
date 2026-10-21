import asyncio
from collections.abc import AsyncIterator
from dataclasses import replace
from io import StringIO
from unittest.mock import AsyncMock

import pytest
from aiomqtt import Message
from loguru import logger
from psycopg import AsyncConnection

import myproj.collection.async_collector as collector
import myproj.collection.async_mqtt as mqtt_pipeline
from myproj.collection.async_mqtt import produce_mqtt, run_mqtt_db_pipeline
from myproj.telemetry.models import TelemetryMessage


def mqtt_message(topic: str, payload: bytes) -> Message:
    return Message(
        topic=topic,
        payload=payload,
        qos=1,
        retain=False,
        mid=1,
        properties=None,
    )


async def fake_messages(inputs: list[Message]) -> AsyncIterator[Message]:
    for message in inputs:
        yield message


def test_produce_mqtt_normal_input(sample_message: TelemetryMessage) -> None:
    expected = [
        sample_message,
        replace(sample_message, device_id="robot-002", sequence_no=1002),
    ]
    inputs = [
        mqtt_message(
            f"tmrp/devices/{message.device_id}/telemetry",
            message.to_json().encode("utf-8"),
        )
        for message in expected
    ]

    async def scenario() -> None:
        queue: asyncio.Queue[TelemetryMessage | None] = asyncio.Queue()
        count = await asyncio.wait_for(
            produce_mqtt(fake_messages(inputs), queue), timeout=1
        )

        assert count == 2
        assert queue.qsize() == 2
        assert [queue.get_nowait(), queue.get_nowait()] == expected
        assert queue.empty()

    asyncio.run(scenario())


@pytest.mark.usefixtures("reset_loguru")
@pytest.mark.parametrize("invalid_kind", ["json", "utf8", "device_id"])
def test_produce_mqtt_skips_invalid_input(
    sample_message: TelemetryMessage, invalid_kind: str
) -> None:
    topic = f"tmrp/devices/{sample_message.device_id}/telemetry"
    payload = sample_message.to_json().encode("utf-8")
    invalid_inputs = {
        "json": mqtt_message(topic, b"{invalid"),
        "utf8": mqtt_message(topic, b"\xff"),
        "device_id": mqtt_message("tmrp/devices/robot-002/telemetry", payload),
    }
    inputs = [invalid_inputs[invalid_kind], mqtt_message(topic, payload)]
    logs = StringIO()
    logger.add(logs, format="{level.name}:{message}")

    async def scenario() -> None:
        queue: asyncio.Queue[TelemetryMessage | None] = asyncio.Queue()
        count = await asyncio.wait_for(
            produce_mqtt(fake_messages(inputs), queue), timeout=1
        )

        assert count == 1
        assert queue.qsize() == 1
        assert queue.get_nowait() == sample_message
        assert queue.empty()

    asyncio.run(scenario())
    entries = logs.getvalue().splitlines()
    assert len(entries) == 1
    assert entries[0].startswith("WARNING:")


def test_produce_mqtt_empty_input() -> None:
    async def scenario() -> None:
        queue: asyncio.Queue[TelemetryMessage | None] = asyncio.Queue()
        count = await asyncio.wait_for(
            produce_mqtt(fake_messages([]), queue), timeout=1
        )

        assert count == 0
        assert queue.empty()

    asyncio.run(scenario())


def test_run_mqtt_db_pipeline(
    sample_message: TelemetryMessage,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    samples = [
        sample_message,
        replace(sample_message, device_id="robot-002", sequence_no=1002),
        replace(sample_message, device_id="robot-002", sequence_no=1003),
        replace(sample_message, device_id="robot-002", sequence_no=1004),
        replace(sample_message, device_id="robot-002", sequence_no=1005),
    ]
    inputs = [
        mqtt_message(
            f"tmrp/devices/{message.device_id}/telemetry",
            message.to_json().encode("utf-8"),
        )
        for message in samples
    ]

    saved_batches: list[list[TelemetryMessage]] = []
    saved_messages: list[TelemetryMessage] = []

    conn = AsyncMock(spec=AsyncConnection)

    async def fake_insert_async(conn, messages):
        saved_batches.append(list(messages))
        saved_messages.extend(messages)
        return len(messages)

    save = AsyncMock(side_effect=fake_insert_async)
    monkeypatch.setattr(collector, "insert_telemetry_batch_async", save)

    async def scenario() -> None:

        inserted = await asyncio.wait_for(
            run_mqtt_db_pipeline(
                fake_messages(inputs),
                conn,
                batch_size=3,
            ),
            timeout=1,
        )

        assert inserted == 5
        assert save.call_count == 2
        assert saved_batches == [
            list(samples[0:3]),
            list(samples[3:]),
        ]
        assert saved_messages == [
            sample_message,
            replace(sample_message, device_id="robot-002", sequence_no=1002),
            replace(sample_message, device_id="robot-002", sequence_no=1003),
            replace(sample_message, device_id="robot-002", sequence_no=1004),
            replace(sample_message, device_id="robot-002", sequence_no=1005),
        ]

    asyncio.run(scenario())


def test_run_mqtt_db_pipeline_partial_insert(
    sample_message: TelemetryMessage,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    expected_1 = [
        sample_message,
        replace(sample_message, sequence_no=sample_message.sequence_no + 1),
        sample_message,
    ]

    expected_2 = [
        replace(sample_message, sequence_no=sample_message.sequence_no + 2),
        replace(sample_message, sequence_no=sample_message.sequence_no + 2),
    ]

    inputs_1 = [
        mqtt_message(
            f"tmrp/devices/{message.device_id}/telemetry",
            message.to_json().encode("utf-8"),
        )
        for message in expected_1
    ]

    inputs_2 = [
        mqtt_message(
            f"tmrp/devices/{message.device_id}/telemetry",
            message.to_json().encode("utf-8"),
        )
        for message in expected_2
    ]

    conn = AsyncMock(spec=AsyncConnection)

    save = AsyncMock(side_effect=[2, 1])
    monkeypatch.setattr(collector, "insert_telemetry_batch_async", save)

    async def scenario() -> None:
        inputs = inputs_1 + inputs_2
        inserted = await asyncio.wait_for(
            run_mqtt_db_pipeline(
                fake_messages(inputs),
                conn,
                batch_size=3,
            ),
            timeout=1,
        )
        assert inserted == 3
        assert save.await_count == 2

    asyncio.run(scenario())


def test_run_mqtt_db_pipeline_empty_input(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = AsyncMock(spec=AsyncConnection)
    save = AsyncMock(side_effect=[])
    monkeypatch.setattr(collector, "insert_telemetry_batch_async", save)

    async def scenario() -> None:
        inserted = await asyncio.wait_for(
            run_mqtt_db_pipeline(
                fake_messages([]),
                conn,
                batch_size=3,
            ),
            timeout=1,
        )
        assert inserted == 0
        assert save.await_count == 0

    asyncio.run(scenario())


def test_run_mqtt_db_pipeline_batch_size_invalid(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = AsyncMock(spec=AsyncConnection)
    save = AsyncMock(side_effect=[2, 1])
    monkeypatch.setattr(collector, "insert_telemetry_batch_async", save)

    async def scenario() -> None:
        with pytest.raises(ValueError):
            await asyncio.wait_for(
                run_mqtt_db_pipeline(
                    fake_messages([]),
                    conn,
                    batch_size=0,
                ),
                timeout=1,
            )

        save.assert_not_called()

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "flush_interval", [0, -1, float("inf"), float("-inf"), float("nan")]
)
def test_run_mqtt_db_pipeline_flush_interval(
    flush_interval,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = AsyncMock(spec=AsyncConnection)
    save = AsyncMock(side_effect=[2, 1])
    monkeypatch.setattr(collector, "insert_telemetry_batch_async", save)

    async def scenario() -> None:

        with pytest.raises(ValueError):
            await asyncio.wait_for(
                run_mqtt_db_pipeline(
                    fake_messages([]),
                    conn,
                    batch_size=3,
                    flush_interval=flush_interval,
                ),
                timeout=1,
            )

        save.assert_not_called()

    asyncio.run(scenario())


def test_run_mqtt_db_pipeline_cancels_input_when_save_fails(
    monkeypatch: pytest.MonkeyPatch,
    sample_message: TelemetryMessage,
) -> None:
    conn = AsyncMock(spec=AsyncConnection)

    async def scenario() -> None:
        input_waiting = asyncio.Event()
        input_finished = asyncio.Event()
        nerver_finish = asyncio.Event()

        failure = RuntimeError("insert failed")

        async def fail_insert(conn, messages):
            await input_waiting.wait()
            raise failure

        save = AsyncMock(side_effect=fail_insert)
        monkeypatch.setattr(collector, "insert_telemetry_batch_async", save)

        async def waiting_messages():
            try:
                yield mqtt_message(
                    f"tmrp/devices/{sample_message.device_id}/telemetry",
                    sample_message.to_json().encode("utf-8"),
                )
                input_waiting.set()
                await nerver_finish.wait()
            finally:
                input_finished.set()

        with pytest.raises(ExceptionGroup) as exc_info:
            await asyncio.wait_for(
                run_mqtt_db_pipeline(
                    waiting_messages(),
                    conn,
                    batch_size=1,
                ),
                timeout=1,
            )

        assert exc_info.value.exceptions == (failure,)
        assert input_finished.is_set()
        save.assert_awaited_once()

    asyncio.run(scenario())


def test_run_mqtt_db_pipeline_cancellation_stops_all_tasks(
    monkeypatch: pytest.MonkeyPatch,
    sample_message: TelemetryMessage,
) -> None:
    conn = AsyncMock(spec=AsyncConnection)

    original_consume = mqtt_pipeline.consume_to_db

    async def scenario() -> None:
        input_started = asyncio.Event()
        input_finished = asyncio.Event()
        consumer_started = asyncio.Event()
        consumer_finished = asyncio.Event()
        nerver_finish = asyncio.Event()

        async def never_insert(conn, messages):
            await nerver_finish.wait()

        save = AsyncMock(side_effect=never_insert)
        monkeypatch.setattr(collector, "insert_telemetry_batch_async", save)

        async def waiting_messages():
            try:
                input_started.set()
                await nerver_finish.wait()
                yield mqtt_message(
                    f"tmrp/devices/{sample_message.device_id}/telemetry",
                    sample_message.to_json().encode("utf-8"),
                )
            finally:
                input_finished.set()

        async def tracked_consumer(queue, conn, batch_size, flush_interval):
            try:
                consumer_started.set()
                return await original_consume(queue, conn, batch_size, flush_interval)
            finally:
                consumer_finished.set()

        monkeypatch.setattr(mqtt_pipeline, "consume_to_db", tracked_consumer)

        task = asyncio.create_task(
            run_mqtt_db_pipeline(waiting_messages(), conn, batch_size=1)
        )
        try:
            await asyncio.wait_for(input_started.wait(), timeout=1)
            await asyncio.wait_for(consumer_started.wait(), timeout=1)

            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(task, timeout=1)

            assert task.cancelled()
            assert consumer_finished.is_set()
            assert input_finished.is_set()
            save.assert_not_called()
        finally:
            if not task.done():
                task.cancel()
            await asyncio.wait_for(
                asyncio.gather(task, return_exceptions=True),
                timeout=1,
            )

    asyncio.run(scenario())
