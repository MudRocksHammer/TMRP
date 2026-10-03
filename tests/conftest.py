from collections.abc import Iterator

import pytest
from loguru import logger


@pytest.fixture
def reset_loguru() -> Iterator[None]:
    """共有Loggerの出力先をテスト間に持ち越さない。"""
    logger.remove()
    try:
        yield
    finally:
        logger.remove()
