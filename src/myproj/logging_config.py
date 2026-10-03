from __future__ import annotations

import json
import sys
from datetime import timezone
from typing import TYPE_CHECKING

from loguru import logger

from myproj.config import AppConfig

if TYPE_CHECKING:
    from loguru import Logger, Message


def configure_logging(config: AppConfig) -> Logger:
    """Loguruの出力先を、アプリ用のJSON標準エラー出力に設定する。"""
    # デフォルト出力と前回の設定を取り除き、二重出力を防ぐ。
    logger.remove()
    stream = sys.stderr

    def write_json(message: Message) -> None:
        record = message.record
        data = {
            "level": record["level"].name,
            "logger": record["extra"].get("logger", record["name"]),
            "message": record["message"],
            "timestamp": record["time"].astimezone(timezone.utc).isoformat(),
        }
        stream.write(json.dumps(data, ensure_ascii=False) + "\n")
        stream.flush()

    logger.add(
        write_json,
        level=config.log_level,
        format="{message}",
        colorize=False,
        backtrace=False,
        diagnose=False,
        catch=False,
    )
    return logger.bind(logger="myproj")
