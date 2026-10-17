import asyncio
from dataclasses import replace
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from psycopg import Connection

import myproj.async_collector as collector
from myproj.models import TelemetryMessage


@pytest.fixture
def sample_message() -> TelemetryMessage:
    project_root = Path(__file__).resolve().parents[2]
    text = (project_root / "examples/telemetry/valid.json").read_text(encoding="utf-8")
    return TelemetryMessage.from_json(text)


def test_async_collector(
    sample_message: TelemetryMessage, monkeypatch: pytest.MonkeyPatch
) -> None:
    conn = AsyncMock(spec=Connection)

    expected = [
        sample_message,
        replace(sample_message, sequence_no=sample_message.sequence_no + 1),
        replace(sample_message, sequence_no=sample_message.sequence_no + 2),
        replace(sample_message, sequence_no=sample_message.sequence_no + 3),
        replace(sample_message, sequence_no=sample_message.sequence_no + 4),
    ]

    save_messages: list[TelemetryMessage] = []

    async def fake_insert_async(conn, messages):
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

        await asyncio.wait_for(queue.join(), timeout=1)

    asyncio.run(scenario())
