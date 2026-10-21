import asyncio
import math
from collections.abc import AsyncIterable
from typing import Any

from aiomqtt import Message
from loguru import logger
from psycopg import AsyncConnection

from myproj.collection.async_collector import consume_to_db
from myproj.collection.mqtt_validation import parse_mqtt_telemetry
from myproj.telemetry.models import TelemetryMessage, TelemetryValidationError


async def produce_mqtt(
    messages: AsyncIterable[Message],
    queue: asyncio.Queue[TelemetryMessage | None],
) -> int:
    res_count = 0
    async for message in messages:
        try:
            msg = parse_mqtt_telemetry(str(message.topic), message.payload)
        except (UnicodeDecodeError, TelemetryValidationError) as e:
            logger.warning(f"Failed to process message: {e}")
            continue

        await queue.put(msg)
        res_count += 1
    return res_count


async def run_mqtt_db_pipeline(
    messages: AsyncIterable[Message],
    conn: AsyncConnection[tuple[Any, ...]],
    batch_size: int = 3,
    flush_interval: float = 1.0,
) -> int:
    if batch_size <= 0:
        raise ValueError("batch_size must be greater than 0")

    if flush_interval <= 0 or not math.isfinite(flush_interval):
        raise ValueError("flush_interval must be greater than 0 and finite")

    queue: asyncio.Queue[TelemetryMessage | None] = asyncio.Queue(maxsize=2)

    async with asyncio.TaskGroup() as tasks:
        consumers = tasks.create_task(
            consume_to_db(
                queue=queue,
                conn=conn,
                batch_size=batch_size,
                flush_interval=flush_interval,
            )
        )

        async with asyncio.TaskGroup() as producers:
            producers.create_task(produce_mqtt(messages, queue))

        await queue.put(None)
        await queue.join()

    return consumers.result()
