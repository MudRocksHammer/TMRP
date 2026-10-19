import asyncio
from typing import Any

from psycopg import AsyncConnection

from myproj.persistence.async_storage import insert_telemetry_batch_async
from myproj.processing.async_pipeline import produce
from myproj.telemetry.models import TelemetryMessage


async def consume_to_db(
    queue: asyncio.Queue[TelemetryMessage | None],
    conn: AsyncConnection[tuple[Any, ...]],
    batch_size: int = 3,
) -> int:
    if batch_size < 1:
        raise ValueError("batch_size must be at least 1")

    pending: list[TelemetryMessage] = []
    total_inserted = 0

    while True:
        msg = await queue.get()
        try:
            if msg is None:
                if pending:
                    total_inserted += await insert_telemetry_batch_async(conn, pending)
                return total_inserted

            pending.append(msg)
            if len(pending) >= batch_size:
                total_inserted += await insert_telemetry_batch_async(conn, pending)
                pending.clear()
        finally:
            queue.task_done()


async def run_db_pipeline(
    groups: dict[str, list[TelemetryMessage]],
    conn: AsyncConnection[tuple[Any, ...]],
    delay: float = 0,
    batch_size: int = 3,
) -> int:
    if batch_size < 1:
        raise ValueError("batch_size must be at least 1")

    queue: asyncio.Queue[TelemetryMessage | None] = asyncio.Queue(maxsize=2)

    async with asyncio.TaskGroup() as tasks:
        consumer = tasks.create_task(consume_to_db(queue, conn, batch_size))

        async with asyncio.TaskGroup() as producers:
            for messages in groups.values():
                producers.create_task(produce(messages, queue, delay))

        # await consumer
        # await producers
        await queue.put(None)
        await queue.join()

    return consumer.result()
