from datetime import datetime, timedelta, timezone
from pathlib import Path

from myproj.models import MessageType, TelemetryMessage


def main() -> None:
    battery_values: dict[str, list[float | None]] = {
        "robot-001": [100.0, 98.0, 96.0, None, 92.0, 90.0],
        "robot-002": [80.0, 78.0, 76.0, 74.0, None, 70.0],
    }
    start_time = datetime(2026, 10, 1, tzinfo=timezone.utc)

    # 実行した場所に関係なく、このプロジェクト内へ出力する。
    project_root = Path(__file__).resolve().parents[1]
    output_path = project_root / "examples/telemetry/analysis.jsonl"
    output_path.parent.mkdir(parents=True, exist_ok=True)

    count = 0
    # 上書きモードなので、繰り返し実行してもデータが増えない。
    with output_path.open("w", encoding="utf-8") as output:
        for device_id, values in battery_values.items():
            # デバイスが変わるたびに連番と時刻を最初から始める。
            for sequence_no, battery in enumerate(values, start=1):
                message = TelemetryMessage(
                    schema_version="1.0",
                    device_id=device_id,
                    sequence_no=sequence_no,
                    event_time=start_time + timedelta(minutes=sequence_no - 1),
                    message_type=MessageType.TELEMETRY,
                    battery_percent=battery,
                )
                # Noneはto_json()によってJSONのnullになる。
                output.write(message.to_json() + "\n")
                count += 1

    print(f"{count}件のTelemetryを生成しました: {output_path}")


if __name__ == "__main__":
    main()
