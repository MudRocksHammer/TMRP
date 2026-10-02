import json
import logging

import pytest

from myproj.config import AppConfig
from myproj.logging_config import JsonFormatter, configure_logging


@pytest.fixture
def log_record():
    record = logging.LogRecord(
        name="myproj.config",
        level=logging.INFO,
        pathname=__file__,
        lineno=10,
        msg="This is a test log message",
        args=(),
        exc_info=None,
    )
    record.created = 0.0
    return record


@pytest.mark.parametrize(
    "level",
    [logging.DEBUG, logging.INFO, logging.WARNING, logging.ERROR, logging.CRITICAL],
)
def test_logger_import_log_level(log_record, level):
    record = log_record
    record.levelno = level
    record.levelname = logging.getLevelName(level)

    json_formatter = JsonFormatter()
    json_output = json.loads(json_formatter.format(record))
    assert json_output["level"] == logging.getLevelName(level)
    assert json_output["logger"] == "myproj.config"
    assert json_output["message"] == "This is a test log message"
    assert json_output["timestamp"] == "1970-01-01T00:00:00+00:00"


@pytest.mark.parametrize(
    "message",
    ["This is a test log message", "Another test message", "日本語で大丈夫かな"],
)
def test_logger_import_message(log_record, message):
    record = log_record
    record.msg = message

    json_formatter = JsonFormatter()
    json_output = json.loads(json_formatter.format(record))
    assert json_output["message"] == message
    assert json_output["logger"] == "myproj.config"
    assert json_output["timestamp"] == "1970-01-01T00:00:00+00:00"


def test_logger_msg_parameter(log_record):
    record = log_record
    record.msg = "loaded: %s"
    record.args = ("config.json",)

    json_output = json.loads(JsonFormatter().format(record))
    assert "loaded: config.json" in json_output["message"]
    assert json_output["logger"] == "myproj.config"
    assert json_output["timestamp"] == "1970-01-01T00:00:00+00:00"


def test_logger_msg_japanese(log_record):
    record = log_record
    record.msg = "日本語のメッセージ: %s"
    record.args = ("パラメータ",)

    json_output = JsonFormatter().format(record)
    assert "日本語のメッセージ: パラメータ" in json_output
    assert json.loads(json_output)["message"] == "日本語のメッセージ: パラメータ"


def test_logger_msg_no_line_break(log_record):
    record = log_record
    record.msg = "1行目\n2行目"

    json_output = JsonFormatter().format(record)
    assert "\n" not in json_output
    assert json.loads(json_output)["message"] == "1行目\n2行目"
    assert json.loads(json_output)["logger"] == "myproj.config"
    assert json.loads(json_output)["timestamp"] == "1970-01-01T00:00:00+00:00"


def test_configure_logging(capsys):
    config = AppConfig(environment="test", log_level="INFO")
    logger = configure_logging(config)

    logger.debug("非表示")
    logger.info("設定を読み込みました")

    captured = capsys.readouterr()

    assert logger.name == "myproj"
    assert logger.level == logging.INFO
    assert captured.out == ""
    assert len(captured.err.splitlines()) == 1

    output = json.loads(captured.err.splitlines()[0])
    assert output["level"] == "INFO"
    assert output["logger"] == "myproj"
    assert output["message"] == "設定を読み込みました"


def test_configure_logging_debug(capsys):
    config = AppConfig(environment="test", log_level="DEBUG")
    logger = configure_logging(config)

    logger.debug("デバッグメッセージ")
    logger.info("情報メッセージ")

    captured = capsys.readouterr()

    assert logger.name == "myproj"
    assert logger.level == logging.DEBUG
    assert captured.out == ""
    assert len(captured.err.splitlines()) == 2

    output_debug = json.loads(captured.err.splitlines()[0])
    assert output_debug["level"] == "DEBUG"
    assert output_debug["logger"] == "myproj"
    assert output_debug["message"] == "デバッグメッセージ"

    output_info = json.loads(captured.err.splitlines()[1])
    assert output_info["level"] == "INFO"
    assert output_info["logger"] == "myproj"
    assert output_info["message"] == "情報メッセージ"


def test_configure_logging_idempotent(capsys):
    config = AppConfig(environment="test", log_level="INFO")
    logger = configure_logging(config)
    logger = configure_logging(config)

    logger.info("設定を読み込みました")

    assert logger is configure_logging(config)
    assert logger.name == "myproj"
    assert logger.level == logging.INFO
    captured = capsys.readouterr()
    assert captured.out == ""
    assert len(captured.err.splitlines()) == 1
    output = json.loads(captured.err.splitlines()[0])
    assert output["level"] == "INFO"
    assert output["logger"] == "myproj"
    assert output["message"] == "設定を読み込みました"
