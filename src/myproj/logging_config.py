from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, TextIO

from loguru import logger

from myproj.config import AppConfig, ConfigLoadError, LogFileConfig

if TYPE_CHECKING:
    from loguru import Logger, Message, Record


def _json_format(record: Record) -> str:
    record["extra"]["json_line"] = json.dumps(
        {
            "level": record["level"].name,
            "logger": record["extra"].get("logger", record["name"]),
            "message": record["message"],
            "timestamp": record["time"].astimezone(timezone.utc).isoformat(),
        },
        ensure_ascii=False,
    )
    return "{extra[json_line]}\n"


class _Rotation:
    """Rotate when any configured size or time condition is reached."""

    def __init__(self, config: LogFileConfig) -> None:
        self.config = config
        self.started = datetime.now().astimezone()
        self.daily_limit = None
        if config.rotation_time is not None:
            hour, minute = map(int, config.rotation_time.split(":"))
            limit = self.started.replace(
                hour=hour, minute=minute, second=0, microsecond=0
            )
            if limit <= self.started:
                limit += timedelta(days=1)
            self.daily_limit = limit

    def __call__(self, message: Message, file: TextIO) -> bool:
        now = message.record["time"]
        file.seek(0, 2)
        size_due = (
            self.config.max_bytes is not None
            and file.tell() > 0
            and file.tell() + len(message.encode("utf-8")) > self.config.max_bytes
        )
        interval_due = (
            self.config.rotation_interval_seconds is not None
            and (now - self.started).total_seconds()
            >= self.config.rotation_interval_seconds
        )
        daily_due = self.daily_limit is not None and now >= self.daily_limit
        if not (size_due or interval_due or daily_due):
            return False
        self.started = now
        if self.daily_limit is not None:
            while self.daily_limit <= now:
                self.daily_limit += timedelta(days=1)
        return True


def configure_logging(config: AppConfig) -> Logger:
    """Configure shared JSON stderr and optional rotating file output."""
    logger.remove()
    if config.log_file is not None:
        file = config.log_file
        rotation = (
            _Rotation(file)
            if any((file.max_bytes, file.rotation_interval_seconds, file.rotation_time))
            else None
        )
        try:
            logger.add(
                file.path,
                level=config.log_level,
                enqueue=config.enqueue,
                format=_json_format,
                rotation=rotation,
                retention=timedelta(days=file.cleanup_days)
                if file.cleanup_days is not None
                else None,
                compression=file.compression,
                delay=file.delay,
                encoding="utf-8",
                colorize=False,
                backtrace=False,
                diagnose=False,
                catch=False,
            )
        except (OSError, ValueError) as e:
            raise ConfigLoadError(
                f"Failed to configure log file {file.path}: {e}"
            ) from e
    logger.add(
        sys.stderr,
        level=config.log_level,
        enqueue=config.enqueue,
        format=_json_format,
        colorize=False,
        backtrace=False,
        diagnose=False,
        catch=False,
    )
    return logger.bind(logger="myproj")
