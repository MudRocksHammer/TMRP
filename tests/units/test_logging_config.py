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


def test_file_json_and_global_reuse(tmp_path, capsys):
    from loguru import logger as shared_logger

    from myproj.config import LogFileConfig

    path = tmp_path / "nested" / "app.log"
    configure_logging(AppConfig(environment="test", log_file=LogFileConfig(str(path))))
    shared_logger.bind(logger="worker").info("中文 {}\n第二行", "{value}")
    entry = json.loads(path.read_text())
    assert entry == json.loads(capsys.readouterr().err)
    assert entry["logger"] == "worker"
    assert entry["message"] == "中文 {value}\n第二行"


def test_size_rotation_zip_and_cleanup(tmp_path):
    import os
    import zipfile

    from loguru import logger as shared_logger

    from myproj.config import LogFileConfig

    old = tmp_path / "app.2000-01-01_00-00-00_000000.log.zip"
    old.write_bytes(b"old")
    os.utime(old, (0, 0))
    path = tmp_path / "app.log"
    log = configure_logging(
        AppConfig(
            environment="test",
            log_file=LogFileConfig(
                str(path), max_bytes=200, cleanup_days=1, compression="zip"
            ),
        )
    )
    log.info("first {}", "a" * 100)
    log.info("second {}", "b" * 100)
    archives = list(tmp_path.glob("*.zip"))
    assert not old.exists()
    assert len(archives) == 1
    with zipfile.ZipFile(archives[0]) as archive:
        assert json.loads(archive.read(archive.namelist()[0]))["message"].startswith(
            "first"
        )
    assert json.loads(path.read_text())["message"].startswith("second")
    shared_logger.remove()


@pytest.mark.parametrize("policy", ["interval", "daily"])
def test_time_rotation(tmp_path, policy):
    from myproj.config import LogFileConfig
    from myproj.logging_config import _Rotation

    config = (
        LogFileConfig("unused", rotation_interval_seconds=60)
        if policy == "interval"
        else LogFileConfig("unused", rotation_time="00:00")
    )
    rotation = _Rotation(config)
    due = (
        rotation.started + timedelta(seconds=60)
        if policy == "interval"
        else rotation.daily_limit
    )
    log = configure_logging(AppConfig(environment="test"))
    messages = []
    from loguru import logger as shared_logger

    shared_logger.add(messages.append, format="{message}")
    log.patch(lambda record: record.update(time=due)).info("time")
    with (tmp_path / "dummy").open("w+") as file:
        assert rotation(messages[0], file)
        assert not rotation(messages[0], file)


def test_delayed_file_creation_and_reconfigure(tmp_path):
    from myproj.config import LogFileConfig

    path = tmp_path / "app.log"
    config = AppConfig(
        environment="test", log_file=LogFileConfig(str(path), delay=True)
    )
    log = configure_logging(config)
    assert not path.exists()
    configure_logging(config)
    log.info("once")
    assert len(path.read_text().splitlines()) == 1


@pytest.mark.parametrize(
    "data",
    [
        {},
        {"path": ""},
        {"path": "x", "max_bytes": True},
        {"path": "x", "cleanup_days": 0},
        {"path": "x", "rotation_interval_seconds": -1},
        {"path": "x", "rotation_time": "24:00"},
        {"path": "x", "compression": "invalid"},
        {"path": "x", "delay": "yes"},
        {"path": "x", "unknown": 1},
        None,
    ],
)
def test_invalid_file_config(data):
    from myproj.config import ConfigValidationError

    with pytest.raises(ConfigValidationError):
        AppConfig.from_dict({"environment": "test", "log_file": data})


@pytest.mark.parametrize("empty", [None, "", "   "])
def test_empty_optional_settings_disable_features(empty, tmp_path):
    import os

    from loguru import logger as shared_logger

    path = tmp_path / "app.log"
    old = tmp_path / "app.2000-01-01_00-00-00_000000.log"
    old.write_text("old")
    os.utime(old, (0, 0))
    config = AppConfig.from_dict(
        {
            "environment": "test",
            "log_file": {
                "path": str(path),
                "max_bytes": empty,
                "rotation_interval_seconds": empty,
                "rotation_time": empty,
                "cleanup_days": empty,
                "compression": empty,
                "delay": empty,
            },
        }
    )
    log = configure_logging(config)
    assert path.exists()
    log.info("first {}", "a" * 10000)
    future = datetime.now().astimezone() + timedelta(days=30)
    log.patch(lambda record: record.update(time=future)).info("second")
    shared_logger.remove()
    assert len(path.read_text().splitlines()) == 2
    assert old.read_text() == "old"
    assert set(tmp_path.iterdir()) == {path, old}


@pytest.mark.parametrize("empty", [None, "", "   "])
def test_empty_settings_do_not_disable_configured_size_rotation(empty, tmp_path):
    from loguru import logger as shared_logger

    path = tmp_path / "app.log"
    config = AppConfig.from_dict(
        {
            "environment": "test",
            "log_file": {
                "path": str(path),
                "max_bytes": 200,
                "rotation_interval_seconds": empty,
                "rotation_time": empty,
                "cleanup_days": empty,
                "compression": empty,
            },
        }
    )
    log = configure_logging(config)
    log.info("first {}", "a" * 100)
    log.info("second {}", "b" * 100)
    shared_logger.remove()
    assert len(list(tmp_path.glob("*.log"))) == 2
    assert json.loads(path.read_text())["message"].startswith("second")


@pytest.mark.parametrize("value", [False, None, "", "   "])
def test_empty_enqueue_is_synchronous(value, capsys):
    config = AppConfig.from_dict({"environment": "test", "enqueue": value})
    assert config.enqueue is False
    log = configure_logging(config)
    log.info("synchronous")
    assert json.loads(capsys.readouterr().err)["message"] == "synchronous"


@pytest.mark.parametrize("value", ["true", 1, [], {}])
def test_invalid_enqueue(value):
    from myproj.config import ConfigValidationError

    with pytest.raises(ConfigValidationError, match="enqueue"):
        AppConfig.from_dict({"environment": "test", "enqueue": value})


def test_enqueue_writes_in_background_and_drains(tmp_path, capsys, monkeypatch):
    import threading

    import myproj.logging_config as logging_config

    path = tmp_path / "app.log"
    thread_ids = []
    original = logging_config._Rotation.__call__

    def track_rotation(self, message, file):
        thread_ids.append(threading.get_ident())
        return original(self, message, file)

    monkeypatch.setattr(logging_config._Rotation, "__call__", track_rotation)
    config = AppConfig.from_dict(
        {
            "environment": "test",
            "enqueue": True,
            "log_file": {"path": str(path), "max_bytes": 100000},
        }
    )
    log = configure_logging(config)
    for i in range(50):
        log.info("中文 {}", i)
    log.complete()
    entries = [json.loads(line) for line in path.read_text().splitlines()]
    assert [entry["message"] for entry in entries] == [f"中文 {i}" for i in range(50)]
    assert entries == [
        json.loads(line) for line in capsys.readouterr().err.splitlines()
    ]
    assert len(thread_ids) == 50
    assert all(thread_id != threading.get_ident() for thread_id in thread_ids)


@pytest.mark.parametrize(
    "telemetry, expected",
    [
        ("examples/telemetry/valid.json", 0),
        ("examples/telemetry/invalid/missing-device-id.json", 1),
    ],
)
def test_async_cli_drains_before_return(tmp_path, telemetry, expected, capsys):
    from myproj.cli import main

    path = tmp_path / "app.log"
    config = tmp_path / "config.json"
    config.write_text(
        json.dumps(
            {
                "environment": "test",
                "enqueue": True,
                "log_file": {"path": str(path)},
            }
        )
    )
    assert main(["validate", telemetry, "--config", str(config)]) == expected
    entries = [json.loads(line) for line in path.read_text().splitlines()]
    assert len(entries) == 1
    assert entries[0]["level"] == ("INFO" if expected == 0 else "ERROR")
    assert entries == [
        json.loads(line) for line in capsys.readouterr().err.splitlines()
    ]
