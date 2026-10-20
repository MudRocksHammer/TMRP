import asyncio
import math
from typing import Any

from psycopg import AsyncConnection

from myproj.persistence.async_storage import insert_telemetry_batch_async
from myproj.processing.async_pipeline import produce
from myproj.telemetry.models import TelemetryMessage


async def consume_to_db(
    queue: asyncio.Queue[TelemetryMessage | None],
    conn: AsyncConnection[tuple[Any, ...]],
    batch_size: int = 3,
    flush_interval: float = 1.0,
) -> int:
    if batch_size < 1:
        raise ValueError("batch_size must be at least 1")

    if flush_interval <= 0 or not math.isfinite(flush_interval):
        raise ValueError("flush_interval must be positive")

    pending: list[TelemetryMessage] = []
    total_inserted = 0
    loop = asyncio.get_running_loop()
    deadline: float | None = None

    while True:
        if not pending:
            msg = await queue.get()
        elif deadline is not None:
            timeout = max(0, deadline - loop.time())
            try:
                msg = await asyncio.wait_for(queue.get(), timeout)
            except asyncio.TimeoutError:
                total_inserted += await insert_telemetry_batch_async(conn, pending)
                pending.clear()
                deadline = None
                continue

        try:
            if msg is None:
                if pending:
                    total_inserted += await insert_telemetry_batch_async(conn, pending)
                return total_inserted

            pending.append(msg)
            if len(pending) == 1:
                deadline = loop.time() + flush_interval
            if len(pending) >= batch_size:
                total_inserted += await insert_telemetry_batch_async(conn, pending)
                pending.clear()
                deadline = None
        finally:
            queue.task_done()


async def run_db_pipeline(
    groups: dict[str, list[TelemetryMessage]],
    conn: AsyncConnection[tuple[Any, ...]],
    delay: float = 0,
    batch_size: int = 3,
    flush_interval: float = 1.0,
) -> int:
    if batch_size < 1:
        raise ValueError("batch_size must be at least 1")

    if flush_interval <= 0 or not math.isfinite(flush_interval):
        raise ValueError("flush_interval must be positive")

    queue: asyncio.Queue[TelemetryMessage | None] = asyncio.Queue(maxsize=2)

    async with asyncio.TaskGroup() as tasks:
        consumer = tasks.create_task(
            consume_to_db(queue, conn, batch_size, flush_interval)
        )

        async with asyncio.TaskGroup() as producers:
            for messages in groups.values():
                producers.create_task(produce(messages, queue, delay))

        await queue.put(None)
        await queue.join()

    return consumer.result()
