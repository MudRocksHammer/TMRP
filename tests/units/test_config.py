import json
from pathlib import Path

import pytest

from myproj.config import AppConfig, ConfigLoadError, ConfigValidationError, load_config


def test_valid_config():
    config_data = {"environment": "development", "log_level": "DEBUG"}
    config = AppConfig.from_dict(config_data)
    assert config.environment == "development"
    assert config.log_level == "DEBUG"


@pytest.mark.parametrize("log_level", ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"])
def test_valid_log_level(log_level):
    config_data = {"environment": "development", "log_level": log_level}
    config = AppConfig.from_dict(config_data)
    assert config.log_level == log_level


@pytest.mark.parametrize("environment", ["development", "test", "production"])
def test_default_log_level(environment):
    config_data = {"environment": environment}
    config = AppConfig.from_dict(config_data)
    assert config.log_level == "INFO"


@pytest.mark.parametrize("environment", ["development", "test", "production"])
def test_valid_environment(environment):
    config_data = {"environment": environment, "log_level": "DEBUG"}
    config = AppConfig.from_dict(config_data)
    assert config.environment == environment


def test_invalid_environment():
    config_data = {"environment": "invalid_env", "log_level": "DEBUG"}
    with pytest.raises(
        ConfigValidationError,
        match="The 'environment'"
        " field must be one of 'development', 'test', or 'production'.",
    ):
        AppConfig.from_dict(config_data)


def test_invalid_missing_environment():
    config_data = {"log_level": "DEBUG"}
    with pytest.raises(
        ConfigValidationError,
        match="Missing required configuration fields: environment",
    ):
        AppConfig.from_dict(config_data)


@pytest.mark.parametrize("environment", ["INVALID", None, 67])
def test_invalid_environment_value(environment):
    config_data = {"environment": environment, "log_level": "DEBUG"}
    with pytest.raises(ConfigValidationError, match="environment"):
        AppConfig.from_dict(config_data)


@pytest.mark.parametrize(
    "log_level",
    ["debug", "info", "warning", "error", "critical", "INVALID", 67, None, "", []],
)
def test_invalid_log_level_value(log_level):
    config_data = {"environment": "development", "log_level": log_level}
    with pytest.raises(ConfigValidationError, match="log_level"):
        AppConfig.from_dict(config_data)


def test_invalid_value_AppConfig():
    with pytest.raises(ConfigValidationError):
        AppConfig(environment="invalid_env", log_level="DEBUG")


@pytest.mark.parametrize(
    "log_level",
    ["debug", "info", "warning", "error", "critical", "INVALID", 67, None, "", []],
)
def test_invalid_AppConfig_log_level(log_level):
    with pytest.raises(ConfigValidationError):
        AppConfig(environment="development", log_level=log_level)


def test_valid_AppConfig_default_log_level():
    config = AppConfig(environment="development")
    assert config.log_level == "INFO"


def test_invalid_unknown_input():
    config_data = {
        "environment": "development",
        "log_level": "DEBUG",
        "unknown_field": "value",
    }
    with pytest.raises(
        ConfigValidationError,
        match="Unknown configuration fields: unknown_field",
    ):
        AppConfig.from_dict(config_data)


def test_invalid_unknown_AppConfig_input():
    with pytest.raises(
        ConfigValidationError,
        match="Unknown configuration fields: unknown_field",
    ):
        AppConfig.from_dict(
            {
                "environment": "development",
                "log_level": "DEBUG",
                "unknown_field": "value",
            }
        )


def test_invalid_non_dict_input():
    non_dict_inputs = ["string", 123, 45.6, None, True, [], ()]
    for input_data in non_dict_inputs:
        with pytest.raises(
            ConfigValidationError,
            match="Configuration data must be a dictionary.",
        ):
            AppConfig.from_dict(input_data)


def test_valid_load_config():
    project_root = Path(__file__).resolve().parents[2]
    path = project_root / "examples/config"
    config_file = path / "valid.json"
    config = load_config(config_file)
    assert config.environment == "development"
    assert config.log_level == "INFO"


@pytest.mark.parametrize(
    "filename",
    ["invalid-log-level.json", "missing-environment.json", "unknown-field.json"],
)
def test_invalid_load_config(filename):
    project_root = Path(__file__).resolve().parents[2]
    path = project_root / "examples/config/invalid"
    config_file = path / filename
    with pytest.raises(ConfigValidationError):
        load_config(config_file)


def test_invalid_load_config_file_not_found(tmp_path: Path):
    config_file = tmp_path / "missing.json"
    with pytest.raises(ConfigLoadError) as exc_info:
        load_config(config_file)

    assert str(config_file) in str(exc_info.value)
    assert isinstance(exc_info.value.__cause__, FileNotFoundError)


def test_invalid_load_config_invalid_json(
    tmp_path: Path,
) -> None:
    config_file = tmp_path / "invalid.json"
    config_file.write_text("{invalid_json: true}", encoding="utf-8")

    with pytest.raises(ConfigLoadError) as exc_info:
        load_config(config_file)

    assert str(config_file) in str(exc_info.value)
    assert isinstance(exc_info.value.__cause__, json.JSONDecodeError)


def test_invalid_load_config_not_utf8(
    tmp_path: Path,
) -> None:
    config_file = tmp_path / "not_utf8.json"
    config_file.write_bytes(b"\xff\xfe\x00\x00")

    with pytest.raises(ConfigLoadError) as exc_info:
        load_config(config_file)

    assert str(config_file) in str(exc_info.value)
    assert isinstance(exc_info.value.__cause__, UnicodeError)


def test_valid_load_config_default_log_level(tmp_path: Path):
    config_file = tmp_path / "default_log_level.json"
    config_file.write_text(json.dumps({"environment": "development"}), encoding="utf-8")
    config = load_config(config_file)
    assert config.environment == "development"
    assert config.log_level == "INFO"
