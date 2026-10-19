import csv
import runpy
import shutil
from collections.abc import Callable
from pathlib import Path

import pytest


@pytest.fixture
def report_runner(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[Callable[[], None], Path]:
    project_root = Path(__file__).resolve().parents[3]

    input_path = tmp_path / "examples/telemetry/battery_alerts.jsonl"
    input_path.parent.mkdir(parents=True)
    shutil.copyfile(
        project_root / "examples/telemetry/battery_alerts.jsonl",
        input_path,
    )

    namespace = runpy.run_path(
        str(project_root / "scripts/analysis/report_battery_alerts.py")
    )
    main = namespace["main"]
    monkeypatch.setitem(main.__globals__, "PROJECT_ROOT", tmp_path)

    return main, tmp_path


def test_report_writes_expected_events(
    report_runner: tuple[Callable[[], None], Path],
) -> None:
    main, tmp_path = report_runner
    main()
    output_path = tmp_path / "reports/battery_alerts.csv"
    assert output_path.exists()
    with output_path.open(encoding="utf-8", newline="") as f:
        reader = csv.reader(f)
        rows = list(reader)
    assert rows[0] == [
        "kind",
        "device_id",
        "sequence_no",
        "event_time",
        "battery_percent",
    ]
    assert len(rows) == 6
    assert rows[1] == ["triggered", "robot-002", "1", "2024-06-01T12:01:00+00:00", "20"]
    assert rows[2] == ["triggered", "robot-001", "2", "2024-06-01T12:02:00+00:00", "20"]
    assert rows[3] == ["recovered", "robot-002", "2", "2024-06-01T12:05:00+00:00", "25"]
    assert rows[4] == ["recovered", "robot-001", "5", "2024-06-01T12:06:00+00:00", "25"]
    assert rows[5] == ["triggered", "robot-001", "6", "2024-06-01T12:07:00+00:00", "20"]


def test_report_is_repeatable(
    report_runner: tuple[Callable[[], None], Path],
) -> None:
    main, tmp_path = report_runner
    main()
    output_path = tmp_path / "reports/battery_alerts.csv"
    with output_path.open(encoding="utf-8", newline="") as f:
        reader = csv.reader(f)
        rows_first_run = list(reader)

    main()
    with output_path.open(encoding="utf-8", newline="") as f:
        reader = csv.reader(f)
        rows_second_run = list(reader)

    assert rows_first_run == rows_second_run


def test_report_empty_input(
    report_runner: tuple[Callable[[], None], Path],
) -> None:
    main, tmp_path = report_runner
    # Overwrite the input file with an empty file
    input_path = tmp_path / "examples/telemetry/battery_alerts.jsonl"
    input_path.write_text("", encoding="utf-8")

    main()
    output_path = tmp_path / "reports/battery_alerts.csv"
    assert output_path.exists()
    with output_path.open(encoding="utf-8", newline="") as f:
        reader = csv.reader(f)
        rows = list(reader)
    # Only the header row should be present
    assert rows[0] == [
        "kind",
        "device_id",
        "sequence_no",
        "event_time",
        "battery_percent",
    ]
    assert len(rows) == 1
