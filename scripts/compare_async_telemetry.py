import asyncio
import time
from pathlib import Path

from myproj.alerts import BatteryAlertEvent, BatteryAlertMonitor
from myproj.async_pipeline import run_pipeline
from myproj.models import TelemetryMessage
from myproj.stream import iter_telemetry


def process_sync(
    messages: list[TelemetryMessage],
    delay: float,
) -> list[BatteryAlertEvent]:
    monitor = BatteryAlertMonitor()

    events: list[BatteryAlertEvent] = []
    for message in messages:
        time.sleep(delay)
        event = monitor.process(message)
        if event is not None:
            events.append(event)
    return events


async def process_async(
    messages: list[TelemetryMessage],
    delay: float,
) -> list[BatteryAlertEvent]:
    monitor = BatteryAlertMonitor()

    events: list[BatteryAlertEvent] = []

    for message in messages:
        await asyncio.sleep(delay)
        event = monitor.process(message)
        if event is not None:
            events.append(event)
    return events


async def run_async(
    groups: dict[str, list[TelemetryMessage]],
    delay: float,
) -> list[list[BatteryAlertEvent]]:
    return await asyncio.gather(
        # * 把这些协程展开成独立参数
        *(process_async(messages, delay) for messages in groups.values())
    )


PROJECT_ROOT = Path(__file__).resolve().parents[1]

if __name__ == "__main__":
    input_file = PROJECT_ROOT / "examples" / "telemetry" / "battery_alerts.jsonl"
    with open(input_file, "r", encoding="utf-8") as f:
        messages = list(iter_telemetry(f))

    delay = 0.2

    groups: dict[str, list[TelemetryMessage]] = {}
    for message in messages:
        groups.setdefault(message.device_id, []).append(message)

    start = time.perf_counter()
    sync_results = [
        process_sync(device_messages, delay) for device_messages in groups.values()
    ]
    sync_time = time.perf_counter()

    # async_results = asyncio.run(run_async(groups, delay))
    async_results = asyncio.run(run_pipeline(groups, delay))

    time_after_async = time.perf_counter()

    print(f"Time taken for synchronous processing: {sync_time - start} seconds")
    print(
        "Time taken for asynchronous processing: "
        f"{time_after_async - sync_time} seconds"
    )

    expected = [event for events in sync_results for event in events]
    assert sorted(async_results, key=lambda e: (e.device_id, e.sequence_no)) == sorted(
        expected, key=lambda e: (e.device_id, e.sequence_no)
    )
    assert len(async_results) == 5
