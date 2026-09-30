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
    assert captured.out.strip() == f"iot-telemetry version:{version('TMRP')}"


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
