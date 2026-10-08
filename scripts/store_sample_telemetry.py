from pathlib import Path

import psycopg

from myproj.models import TelemetryMessage
from myproj.storage import insert_telemetry


def main() -> None:
    # read file from examples/telemetry/valid.json
    file_path = Path(__file__).resolve().parents[1]
    with open(file_path / "examples/telemetry/valid.json", "r", encoding="utf-8") as f:
        telemetry_data = TelemetryMessage.from_json(f.read())

    with psycopg.connect(
        "host=/var/run/postgresql port=5432 dbname=tmrp_dev user=shou",
        options="-c timezone=UTC",
    ) as conn:
        inserted = insert_telemetry(conn, telemetry_data)

    if not inserted:
        print("同じイベントが保存済みのため、追加しませんでした")
    else:
        print("Telemetry data inserted successfully")


if __name__ == "__main__":
    main()
