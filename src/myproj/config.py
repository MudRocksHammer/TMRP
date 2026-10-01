import json
from dataclasses import dataclass
from pathlib import Path
from typing import Self


class ConfigValidationError(ValueError):
    """Exception raised for errors in the configuration validation."""


class ConfigLoadError(ValueError):
    """Exception raised for errors in loading the configuration."""


@dataclass
class AppConfig:
    environment: str
    log_level: str = "INFO"

    def __post_init__(self) -> None:
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
                "'INFO', 'WARNING', 'ERROR', or 'CRITICAL'."
            )

    @classmethod
    def from_dict(cls, data: object) -> Self:
        if not isinstance(data, dict):
            raise ConfigValidationError("Configuration data must be a dictionary.")
        required_fields = {"environment"}

        missing = required_fields - data.keys()
        unknown = data.keys() - required_fields - {"log_level"}

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

        return cls(environment=environment, log_level=log_level)


def load_config(path: Path) -> AppConfig:
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError, UnicodeError) as e:
        raise ConfigLoadError(f"Failed to load configuration from {path}: {e}") from e
    return AppConfig.from_dict(data)
