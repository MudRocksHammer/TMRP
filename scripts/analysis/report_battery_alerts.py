import csv
from pathlib import Path

from myproj.alerts.battery import BatteryAlertMonitor
from myproj.telemetry.stream import iter_telemetry

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def main() -> None:
    input_file = PROJECT_ROOT / "examples" / "telemetry" / "battery_alerts.jsonl"
    with open(input_file, "r", encoding="utf-8") as f:
        messages = list(iter_telemetry(f))

    monitor = BatteryAlertMonitor()
    output_file = PROJECT_ROOT / "reports/battery_alerts.csv"
    output_file.parent.mkdir(parents=True, exist_ok=True)
    with open(output_file, "w", encoding="utf-8", newline="") as csvfile:
        writer = csv.writer(csvfile)
        writer.writerow(
            ["kind", "device_id", "sequence_no", "event_time", "battery_percent"]
        )
        for message in messages:
            res = monitor.process(message)
            if res is not None:
                print(res)
                writer.writerow(
                    [
                        res.kind.value,
                        res.device_id,
                        res.sequence_no,
                        res.event_time.isoformat(),
                        res.battery_percent,
                    ]
                )


if __name__ == "__main__":
    main()
