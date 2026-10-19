import json
from dataclasses import dataclass, fields
from datetime import time
from pathlib import Path
from typing import Self


class ConfigValidationError(ValueError):
    """Exception raised for errors in the configuration validation."""


class ConfigLoadError(ValueError):
    """Exception raised for errors in loading the configuration."""


@dataclass
class LogFileConfig:
    path: str
    max_bytes: int | None = None
    rotation_interval_seconds: int | None = None
    rotation_time: str | None = None
    cleanup_days: int | None = None
    compression: str | None = None
    delay: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.path, str) or not self.path.strip():
            raise ConfigValidationError("log_file.path must be a non-empty string.")
        # Empty optional settings disable their feature, just like omitted values.
        for name in (
            "max_bytes",
            "rotation_interval_seconds",
            "rotation_time",
            "cleanup_days",
            "compression",
            "delay",
        ):
            value = getattr(self, name)
            # read the value and normalize empty strings to None (or False for delay)
            if value is None or (isinstance(value, str) and not value.strip()):
                setattr(self, name, False if name == "delay" else None)
        for name in ("max_bytes", "rotation_interval_seconds", "cleanup_days"):
            value = getattr(self, name)
            if value is not None and (type(value) is not int or value <= 0):
                raise ConfigValidationError(
                    f"log_file.{name} must be a positive integer."
                )
        if self.rotation_time is not None:
            try:
                if (
                    not isinstance(self.rotation_time, str)
                    or len(self.rotation_time) != 5
                    or self.rotation_time[2] != ":"
                ):
                    raise ValueError
                time.fromisoformat(self.rotation_time)
            except ValueError as e:
                raise ConfigValidationError(
                    "log_file.rotation_time must be HH:MM (00:00 to 23:59)."
                ) from e
        if self.compression not in (None, "zip", "gz", "bz2", "xz"):
            raise ConfigValidationError(
                "log_file.compression must be zip, gz, bz2, xz or null."
            )
        if type(self.delay) is not bool:
            raise ConfigValidationError("log_file.delay must be a boolean.")

    @classmethod
    def from_dict(cls, data: object) -> Self:
        if not isinstance(data, dict):
            raise ConfigValidationError("log_file must be an object.")
        unknown = data.keys() - {field.name for field in fields(cls)}
        if unknown or "path" not in data:
            raise ConfigValidationError(
                "log_file requires path and rejects unknown fields."
            )
        return cls(**data)


@dataclass
class AppConfig:
    environment: str
    log_level: str = "INFO"
    log_file: LogFileConfig | None = None
    enqueue: bool = False

    def __post_init__(self) -> None:
        if self.enqueue is None or (
            isinstance(self.enqueue, str) and not self.enqueue.strip()
        ):
            self.enqueue = False
        if type(self.enqueue) is not bool:
            raise ConfigValidationError("The 'enqueue' field must be a boolean.")
        if self.log_file is not None and not isinstance(self.log_file, LogFileConfig):
            raise ConfigValidationError("log_file must be a LogFileConfig instance.")
        if not isinstance(self.environment, str) or self.environment not in {
            "development",
            "test",
            "production",
        }:
            raise ConfigValidationError(
                "The 'environment' "
                "field must be one of 'development', 'test', or 'production'."
            )
        if not isinstance(self.log_level, str) or self.log_level not in {
            "DEBUG",
            "INFO",
            "WARNING",
            "ERROR",
            "CRITICAL",
        }:
            raise ConfigValidationError(
                "The 'log_level' field must be one of 'DEBUG', "
                "'INFO', 'WARNING', 'ERROR', or 'CRITICAL'. "
                f"Received: {self.log_level}"
            )

    @classmethod
    def from_dict(cls, data: object) -> Self:
        if not isinstance(data, dict):
            raise ConfigValidationError("Configuration data must be a dictionary.")
        required_fields = {"environment"}

        missing = required_fields - data.keys()
        unknown = data.keys() - required_fields - {"log_level", "log_file", "enqueue"}

        if missing:
            raise ConfigValidationError(
                f"Missing required configuration fields: {', '.join(missing)}"
            )
        if unknown:
            raise ConfigValidationError(
                f"Unknown configuration fields: {', '.join(unknown)}"
            )

        environment = data["environment"]
        if not isinstance(environment, str):
            raise ConfigValidationError("The 'environment' field must be a string.")

        log_level = data.get("log_level", "INFO")
        if not isinstance(log_level, str):
            raise ConfigValidationError("The 'log_level' field must be a string.")

        return cls(
            environment=environment,
            log_level=log_level,
            enqueue=data.get("enqueue", False),
            log_file=LogFileConfig.from_dict(data["log_file"])
            if "log_file" in data
            else None,
        )


def load_config(path: Path) -> AppConfig:
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError, UnicodeError) as e:
        raise ConfigLoadError(f"Failed to load configuration from {path}: {e}") from e
    return AppConfig.from_dict(data)
