import asyncio
from pathlib import Path

import pytest

import myproj.async_pipeline as async_pipeline
from myproj.alerts import BatteryAlertEvent
from myproj.async_pipeline import consume, produce, run_pipeline
from myproj.models import TelemetryMessage
from myproj.stream import iter_telemetry


@pytest.fixture
def battery_alerts() -> list[TelemetryMessage]:
    project_root = Path(__file__).resolve().parents[2]

    input_file = project_root / "examples/telemetry/battery_alerts.jsonl"
    with open(input_file, "r", encoding="utf-8") as f:
        return list(iter_telemetry(f))


def test_pipeline_returns_expected_events(
    battery_alerts: list[TelemetryMessage],
) -> None:
    async def scenario() -> None:
        groups: dict[str, list[TelemetryMessage]] = {}
        for message in battery_alerts:
            groups.setdefault(message.device_id, []).append(message)
        events = await asyncio.wait_for(
            run_pipeline(groups, delay=0),
            timeout=1,
        )

        assert len(events) == 5
        actual = [
            (
                event.device_id,
                event.sequence_no,
                event.kind.value,
                event.event_time.isoformat(),
                event.battery_percent,
            )
            for event in sorted(events, key=lambda e: (e.device_id, e.sequence_no))
        ]
        expected = [
            ("robot-001", 2, "triggered", "2024-06-01T12:02:00+00:00", 20),
            ("robot-001", 5, "recovered", "2024-06-01T12:06:00+00:00", 25),
            ("robot-001", 6, "triggered", "2024-06-01T12:07:00+00:00", 20),
            ("robot-002", 1, "triggered", "2024-06-01T12:01:00+00:00", 20),
            ("robot-002", 2, "recovered", "2024-06-01T12:05:00+00:00", 25),
        ]
        assert actual == expected

    asyncio.run(scenario())


@pytest.mark.parametrize("group", [{}, {"robot-001": []}])
def test_pipeline_empty_input(group: dict[str, list[TelemetryMessage]]) -> None:
    async def scenario() -> None:
        events = await asyncio.wait_for(
            run_pipeline(group, delay=0),
            timeout=1,
        )
        assert events == []

    asyncio.run(scenario())


def test_consumer_finishes_on_sentinel() -> None:
    async def scenario() -> None:
        queue: asyncio.Queue[TelemetryMessage | None] = asyncio.Queue()
        await queue.put(None)

        events = await asyncio.wait_for(consume(queue), timeout=1)
        assert events == []

        await asyncio.wait_for(queue.join(), timeout=1)
        assert queue.empty()

    asyncio.run(scenario())


class ObservedQueue(asyncio.Queue[TelemetryMessage | None]):
    def __init__(self) -> None:
        super().__init__(maxsize=1)
        self.put_when_full = asyncio.Event()

    async def put(self, item: TelemetryMessage | None) -> None:
        if self.full():
            self.put_when_full.set()

        await super().put(item)


def test_producer_waits_until_queue_has_space(
    battery_alerts: list[TelemetryMessage],
) -> None:
    async def scenario() -> None:
        queue: ObservedQueue = ObservedQueue()

        queue.put_nowait(battery_alerts[0])
        producer_task = asyncio.create_task(produce([battery_alerts[1]], queue, 0))

        await asyncio.wait_for(queue.put_when_full.wait(), timeout=1)

        assert not producer_task.done()
        assert queue.qsize() == 1

        assert queue.get_nowait() == battery_alerts[0]
        queue.task_done()

        await asyncio.wait_for(producer_task, timeout=1)

        assert queue.get_nowait() == battery_alerts[1]
        queue.task_done()

        await asyncio.wait_for(queue.join(), timeout=1)
        assert queue.empty()

    asyncio.run(scenario())


def test_pipeline_cancels_producer_when_consumer_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        started = asyncio.Event()
        finished = asyncio.Event()
        nerver_finish = asyncio.Event()
        failure = RuntimeError("consumer failed")

        async def blocked_produce(
            messages: list[TelemetryMessage],
            queue: asyncio.Queue[TelemetryMessage | None],
            delay: float,
        ) -> None:
            try:
                started.set()
                await nerver_finish.wait()
            finally:
                finished.set()

        async def failing_consume(
            queue: asyncio.Queue[TelemetryMessage | None],
        ) -> list[BatteryAlertEvent]:
            await started.wait()
            raise failure

        monkeypatch.setattr(async_pipeline, "produce", blocked_produce)
        monkeypatch.setattr(async_pipeline, "consume", failing_consume)

        with pytest.raises(ExceptionGroup) as exc_info:
            await asyncio.wait_for(
                async_pipeline.run_pipeline({"robot-001": []}, delay=1), timeout=1
            )

        assert exc_info.value.exceptions == (failure,)
        assert finished.is_set()

    asyncio.run(scenario())


def test_pipeline_cancellation_stops_all_tasks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        producer_started = asyncio.Event()
        consumer_started = asyncio.Event()
        producer_finished = asyncio.Event()
        consumer_finished = asyncio.Event()
        never_finish = asyncio.Event()

        async def blocked_produce(
            messages: list[TelemetryMessage],
            queue: asyncio.Queue[TelemetryMessage | None],
            delay: float,
        ) -> None:
            try:
                producer_started.set()
                await never_finish.wait()
            finally:
                producer_finished.set()

        origin_consume = async_pipeline.consume

        async def tracked_consume(
            queue: asyncio.Queue[TelemetryMessage | None],
        ) -> list[BatteryAlertEvent]:
            try:
                consumer_started.set()
                return await origin_consume(queue)
            finally:
                consumer_finished.set()

        monkeypatch.setattr(async_pipeline, "produce", blocked_produce)
        monkeypatch.setattr(async_pipeline, "consume", tracked_consume)

        pipeline_task = asyncio.create_task(
            async_pipeline.run_pipeline({"robot-001": []}, delay=0)
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
