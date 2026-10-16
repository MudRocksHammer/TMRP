import asyncio

from myproj.alerts import BatteryAlertEvent, BatteryAlertMonitor
from myproj.models import TelemetryMessage


async def produce(
    messages: list[TelemetryMessage],
    queue: asyncio.Queue[TelemetryMessage | None],
    delay: float,
) -> None:
    for message in messages:
        await asyncio.sleep(delay)
        await queue.put(message)


async def consume(
    queue: asyncio.Queue[TelemetryMessage | None],
) -> list[BatteryAlertEvent]:
    events: list[BatteryAlertEvent] = []
    monitor = BatteryAlertMonitor()

    while True:
        item = await queue.get()
        try:
            if item is None:
                return events
            event = monitor.process(item)
            if event is not None:
                events.append(event)
        finally:
            queue.task_done()


async def run_pipeline(
    groups: dict[str, list[TelemetryMessage]],
    delay: float,
) -> list[BatteryAlertEvent]:
    queue: asyncio.Queue[TelemetryMessage | None] = asyncio.Queue(maxsize=2)

    async with asyncio.TaskGroup() as tasks:
        # 消费者启动
        consumer = tasks.create_task(consume(queue))

        # 内层任务组，生产者将消息放入队列
        async with asyncio.TaskGroup() as producers:
            for messages in groups.values():
                producers.create_task(produce(messages, queue, delay))

        await queue.put(None)
        await queue.join()

    return consumer.result()
