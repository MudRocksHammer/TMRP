import json
from datetime import datetime, timedelta, timezone

import pytest

from myproj.config import AppConfig
from myproj.logging_config import configure_logging

pytestmark = pytest.mark.usefixtures("reset_loguru")


@pytest.mark.parametrize("level", ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"])
def test_json_log_level(level, capsys):
    logger = configure_logging(AppConfig(environment="test", log_level="DEBUG"))
    logger.log(level, "テストメッセージ")

    captured = capsys.readouterr()
    assert captured.out == ""
    assert len(captured.err.splitlines()) == 1
    output = json.loads(captured.err)
    assert set(output) == {"level", "logger", "message", "timestamp"}
    assert output["level"] == level
    assert output["logger"] == "myproj"
    assert output["message"] == "テストメッセージ"


def test_json_timestamp_is_normalized_to_utc(capsys):
    logger = configure_logging(AppConfig(environment="test"))
    # UTC+9の時刻を渡し、同じ瞬間をUTCで表現することを確認する。
    fixed_time = datetime(1970, 1, 1, 9, tzinfo=timezone(timedelta(hours=9)))
    logger = logger.patch(lambda record: record.update(time=fixed_time))
    logger.info("時刻の確認")

    output = json.loads(capsys.readouterr().err)
    assert output["timestamp"] == "1970-01-01T00:00:00+00:00"


@pytest.mark.parametrize(
    "message",
    ["This is a test log message", '引用符: "value" と {braces}', "日本語で大丈夫かな"],
)
def test_json_message_round_trip(message, capsys):
    logger = configure_logging(AppConfig(environment="test"))
    logger.info(message)

    output = json.loads(capsys.readouterr().err)
    assert output["message"] == message


def test_loguru_message_arguments(capsys):
    logger = configure_logging(AppConfig(environment="test"))
    logger.info("loaded: {}", "config.json")

    output = json.loads(capsys.readouterr().err)
    assert output["message"] == "loaded: config.json"


def test_json_keeps_japanese_readable(capsys):
    logger = configure_logging(AppConfig(environment="test"))
    logger.info("日本語のメッセージ: {}", "パラメータ")

    text = capsys.readouterr().err
    assert "日本語のメッセージ: パラメータ" in text
    assert json.loads(text)["message"] == "日本語のメッセージ: パラメータ"


def test_message_newline_stays_inside_one_json_line(capsys):
    logger = configure_logging(AppConfig(environment="test"))
    logger.info("1行目\n2行目")

    lines = capsys.readouterr().err.splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["message"] == "1行目\n2行目"


@pytest.mark.parametrize(
    ("configured_level", "expected_levels"),
    [
        ("DEBUG", ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]),
        ("INFO", ["INFO", "WARNING", "ERROR", "CRITICAL"]),
        ("WARNING", ["WARNING", "ERROR", "CRITICAL"]),
        ("ERROR", ["ERROR", "CRITICAL"]),
        ("CRITICAL", ["CRITICAL"]),
    ],
)
def test_log_level_filters_output(configured_level, expected_levels, capsys):
    logger = configure_logging(
        AppConfig(environment="test", log_level=configured_level)
    )
    for level in ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"):
        logger.log(level, "{}のメッセージ", level)

    captured = capsys.readouterr()
    assert captured.out == ""
    entries = [json.loads(line) for line in captured.err.splitlines()]
    assert [entry["level"] for entry in entries] == expected_levels
    assert [entry["message"] for entry in entries] == [
        f"{level}のメッセージ" for level in expected_levels
    ]


def test_repeated_setup_does_not_duplicate_logs(capsys):
    config = AppConfig(environment="test")
    configure_logging(config)
    logger = configure_logging(config)
    logger.info("一度だけ")

    captured = capsys.readouterr()
    assert captured.out == ""
    lines = captured.err.splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["message"] == "一度だけ"


def test_reconfiguration_updates_level_for_existing_logger(capsys):
    logger = configure_logging(AppConfig(environment="test", log_level="INFO"))
    configure_logging(AppConfig(environment="test", log_level="ERROR"))
    logger.info("非表示")
    logger.error("エラーのみ表示")

    lines = capsys.readouterr().err.splitlines()
    assert len(lines) == 1
    output = json.loads(lines[0])
    assert output["level"] == "ERROR"
    assert output["message"] == "エラーのみ表示"
