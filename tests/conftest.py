from collections.abc import Iterator
from pathlib import Path

import pytest
from loguru import logger

from myproj.telemetry.models import TelemetryMessage


@pytest.fixture
def reset_loguru() -> Iterator[None]:
    """共有Loggerの出力先をテスト間に持ち越さない。"""
    logger.remove()
    try:
        yield
    finally:
        logger.remove()


@pytest.fixture
def sample_message() -> TelemetryMessage:
    project_root = Path(__file__).resolve().parents[1]
    text = (project_root / "examples/telemetry/valid.json").read_text(encoding="utf-8")
    return TelemetryMessage.from_json(text)
