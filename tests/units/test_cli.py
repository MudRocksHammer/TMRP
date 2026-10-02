import json
import logging
from collections.abc import Iterator
from importlib.metadata import version
from pathlib import Path

import pytest

from myproj.cli import main


def test_validate_missing_file(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    path = tmp_path / "missing_file.json"

    exit_code = main(["validate", str(path)])
    captured = capsys.readouterr()

    assert exit_code == 1
    assert captured.out == ""
    assert "Error" in captured.err
    assert "missing_file.json" in captured.err
    assert "Traceback" not in captured.err


def test_missing_arguments(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as exc_info:
        main([])

    captured = capsys.readouterr()

    assert exc_info.value.code == 2
    assert captured.out == ""
    assert "usage" in captured.err


def test_version(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc_info:
        main(["--version"])
    captured = capsys.readouterr()

    assert exc_info.value.code == 0
    assert captured.err == ""
    assert captured.out.strip() == f"tmrp version:{version('TMRP')}"


def test_validate_valid_JSON(
    capsys: pytest.CaptureFixture[str],
) -> None:
    project_root = Path(__file__).resolve().parents[2]
    path = project_root / "examples/telemetry/valid.json"

    exit_code = main(["validate", str(path)])
    captured = capsys.readouterr()

    assert exit_code == 0
    assert captured.err == ""
    assert "device_id=robot-001" in captured.out
    assert "sequence_no=1001" in captured.out
    assert "event_time=2024-06-01T12:00:00+00:00" in captured.out


def test_validate_invalid_JSON(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    path = tmp_path / "invalid.json"
    path.write_text("{ invalid json }")

    exit_code = main(["validate", str(path)])
    captured = capsys.readouterr()

    assert exit_code == 1
    assert captured.out == ""
    assert "Error" in captured.err
    assert "invalid json" in captured.err.lower()
    assert "Traceback" not in captured.err


def test_validate_invalid_JSON_missing_device_id(
    capsys: pytest.CaptureFixture[str],
) -> None:
    project_root = Path(__file__).resolve().parents[2]
    path = project_root / "examples/telemetry/invalid/missing-device-id.json"

    exit_code = main(["validate", str(path)])
    captured = capsys.readouterr()

    assert exit_code == 1
    assert captured.out == ""
    assert "Error" in captured.err
    assert "device_id" in captured.err
    assert "missing required fields" in captured.err.lower()
    assert "Traceback" not in captured.err


def test_validate_missing_JSON_file(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    path = tmp_path / "missing.json"

    exit_code = main(["validate", str(path)])
    captured = capsys.readouterr()

    assert exit_code == 1
    assert captured.out == ""
    assert "Error" in captured.err
    assert "missing.json" in captured.err
    assert "Traceback" not in captured.err


def test_validate_directory_instead_of_file(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    path = tmp_path / "directory"
    path.mkdir()

    exit_code = main(["validate", str(path)])
    captured = capsys.readouterr()

    assert exit_code == 1
    assert captured.out == ""
    assert "Error" in captured.err
    assert "directory" in captured.err
    assert "Traceback" not in captured.err


def test_validate_not_utf8(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    path = tmp_path / "not_utf8.json"
    path.write_bytes(b"\xff\xfe\x00\x00")

    exit_code = main(["validate", str(path)])
    captured = capsys.readouterr()

    assert exit_code == 1
    assert captured.out == ""
    assert "Error" in captured.err
    assert "Traceback" not in captured.err


def test_validate_no_parameters(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as exc_info:
        main(["validate"])
    captured = capsys.readouterr()

    assert exc_info.value.code == 2
    assert captured.out == ""
    assert "error" in captured.err
    assert "Traceback" not in captured.err


def test_check_config_valid(
    capsys: pytest.CaptureFixture[str],
) -> None:
    project_root = Path(__file__).resolve().parents[2]
    path = project_root / "examples/config/valid.json"

    exit_code = main(["check-config", str(path)])
    captured = capsys.readouterr()

    assert exit_code == 0
    assert captured.out != ""
    assert captured.out.strip() == "environment=development log_level=INFO"
    assert captured.err == ""
    assert "Error" not in captured.err
    assert "Traceback" not in captured.err


def test_check_config_missing_file(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    path = tmp_path / "missing.json"

    exit_code = main(["check-config", str(path)])
    captured = capsys.readouterr()

    assert exit_code == 1
    assert captured.out == ""
    assert "Error" in captured.err
    assert "missing.json" in captured.err
    assert "Traceback" not in captured.err


def test_check_config_directory_instead_of_file(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    path = tmp_path / "directory"
    path.mkdir()

    exit_code = main(["check-config", str(path)])
    captured = capsys.readouterr()

    assert exit_code == 1
    assert captured.out == ""
    assert "Error" in captured.err
    assert "directory" in captured.err
    assert "Traceback" not in captured.err


def test_check_config_no_parameters(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as exc_info:
        main(["check-config"])
    captured = capsys.readouterr()

    assert exc_info.value.code == 2
    assert captured.out == ""
    assert "error" in captured.err
    assert "Traceback" not in captured.err


def test_check_config_not_utf8(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    path = tmp_path / "not_utf8.json"
    path.write_bytes(b"\xff\xfe\x00\x00")

    exit_code = main(["check-config", str(path)])
    captured = capsys.readouterr()

    assert exit_code == 1
    assert captured.out == ""
    assert "Error" in captured.err
    assert "Traceback" not in captured.err


def test_check_config_invalid_json(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    path = tmp_path / "invalid.json"
    path.write_text("{invalid_json:}", encoding="utf-8")

    exit_code = main(["check-config", str(path)])
    captured = capsys.readouterr()

    assert exit_code == 1
    assert captured.out == ""
    assert "Error" in captured.err
    assert str(path) in captured.err
    assert "Traceback" not in captured.err


def test_check_config_default_log_level(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    path = tmp_path / "default_log_level.json"
    path.write_text('{"environment": "development"}', encoding="utf-8")

    exit_code = main(["check-config", str(path)])
    captured = capsys.readouterr()

    assert exit_code == 0
    assert captured.out != ""
    assert "log_level=INFO" in captured.out
    assert captured.err == ""
    assert "Error" not in captured.err
    assert "Traceback" not in captured.err


def test_check_config_wrong_log_level(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    path = tmp_path / "wrong_log_level.json"
    path.write_text(
        '{"environment": "development", "log_level": "VERBOSE"}', encoding="utf-8"
    )

    exit_code = main(["check-config", str(path)])
    captured = capsys.readouterr()

    assert exit_code == 1
    assert captured.out == ""
    assert "Error" in captured.err
    assert "log_level" in captured.err
    assert "Traceback" not in captured.err


@pytest.fixture
def telemetry_path(tmp_path: Path) -> Path:
    """実在する正常データを、テストごとに独立したファイルへコピーする。"""
    sample = Path(__file__).resolve().parents[2] / "examples/telemetry/valid.json"
    path = tmp_path / "telemetry.json"
    path.write_text(sample.read_text(encoding="utf-8"), encoding="utf-8")
    return path


@pytest.fixture
def config_path(tmp_path: Path) -> Iterator[Path]:
    """設定ファイルを用意し、テスト後に共有Loggerの状態を戻す。"""
    path = tmp_path / "config.json"
    path.write_text(
        json.dumps({"environment": "test", "log_level": "INFO"}),
        encoding="utf-8",
    )

    # getLoggerは同じ名前のLoggerを再利用するため、テスト間の影響を防ぐ。
    logger = logging.getLogger("myproj")
    original_handlers = logger.handlers[:]
    original_level = logger.level
    original_propagate = logger.propagate
    for handler in original_handlers:
        logger.removeHandler(handler)
    try:
        yield path
    finally:
        # capsysの出力先を使うHandlerを、テスト終了時に取り外す。
        for handler in logger.handlers[:]:
            logger.removeHandler(handler)
            handler.close()
        for handler in original_handlers:
            logger.addHandler(handler)
        logger.setLevel(original_level)
        logger.propagate = original_propagate


@pytest.mark.parametrize("log_level", ["INFO", "WARNING"])
def test_validate_with_config_success(
    telemetry_path: Path,
    config_path: Path,
    capsys: pytest.CaptureFixture[str],
    log_level: str,
) -> None:
    config_path.write_text(
        json.dumps({"environment": "test", "log_level": log_level}),
        encoding="utf-8",
    )

    # 位置引数はTelemetry、--configの値はアプリの設定ファイル。
    exit_code = main(["validate", str(telemetry_path), "--config", str(config_path)])
    captured = capsys.readouterr()

    assert exit_code == 0
    assert captured.out.strip() == (
        "device_id=robot-001 sequence_no=1001 event_time=2024-06-01T12:00:00+00:00"
    )
    if log_level == "WARNING":
        assert captured.err == ""
    else:
        lines = captured.err.splitlines()
        assert len(lines) == 1
        entry = json.loads(lines[0])
        assert entry["level"] == "INFO"
        assert entry["logger"] == "myproj"
        assert "robot-001" in entry["message"]
        assert "1001" in entry["message"]


def test_validate_with_config_invalid_telemetry(
    telemetry_path: Path,
    config_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # ファイル不存在ではなく、必須項目の欠落で失敗させる。
    data = json.loads(telemetry_path.read_text(encoding="utf-8"))
    del data["device_id"]
    telemetry_path.write_text(json.dumps(data), encoding="utf-8")

    exit_code = main(["validate", str(telemetry_path), "--config", str(config_path)])
    captured = capsys.readouterr()

    assert exit_code == 1
    assert captured.out == ""
    lines = captured.err.splitlines()
    assert len(lines) == 1, "設定指定時のエラーはJSONログ1行だけにする"
    entry = json.loads(lines[0])
    assert entry["level"] == "ERROR"
    assert entry["logger"] == "myproj"
    assert "device_id" in entry["message"]
    assert "Traceback" not in captured.err


def test_validate_with_missing_config(
    telemetry_path: Path,
    config_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config_path.unlink()

    exit_code = main(["validate", str(telemetry_path), "--config", str(config_path)])
    captured = capsys.readouterr()

    assert exit_code == 1
    assert captured.out == ""
    assert captured.err.startswith("Error:")
    assert str(config_path) in captured.err
    assert "Traceback" not in captured.err


def test_validate_with_invalid_config(
    telemetry_path: Path,
    config_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config_path.write_text(
        json.dumps({"environment": "test", "log_level": "VERBOSE"}),
        encoding="utf-8",
    )

    exit_code = main(["validate", str(telemetry_path), "--config", str(config_path)])
    captured = capsys.readouterr()

    assert exit_code == 1
    assert captured.out == ""
    assert captured.err.startswith("Error:")
    assert "log_level" in captured.err
    assert "Traceback" not in captured.err


def test_validate_without_config_after_configured_call(
    telemetry_path: Path,
    config_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # 同一プロセスで設定付き実行の後に、設定なしで実行する。
    first_exit = main(["validate", str(telemetry_path), "--config", str(config_path)])
    first_output = capsys.readouterr()
    assert first_exit == 0
    assert len(first_output.err.splitlines()) == 1

    exit_code = main(["validate", str(telemetry_path)])
    captured = capsys.readouterr()

    assert exit_code == 0
    assert captured.out == first_output.out
    assert captured.err == ""
