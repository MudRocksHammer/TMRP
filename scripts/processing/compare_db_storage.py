import asyncio
import csv
import time
from dataclasses import replace
from pathlib import Path
from statistics import median
from typing import Any

import psycopg
from openpyxl import Workbook
from openpyxl.styles import Font
from openpyxl.utils import get_column_letter

from myproj.persistence.async_storage import (
    insert_telemetry_batch_async,
    insert_telemetry_batch_async_multi,
)
from myproj.persistence.storage import (
    insert_telemetry_batch,
    insert_telemetry_batch_multi,
)
from myproj.telemetry.models import TelemetryMessage

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DSN = "host=/var/run/postgresql port=5432 dbname=tmrp_dev user=shou"
CONNECTION_OPTIONS = "-c timezone=UTC -c search_path=pg_temp"
REPORT_FIELDS = (
    "mode",
    "run",
    "message_count",
    "batch_size",
    "inserted_count",
    "elapsed_seconds",
)
REPORT_MODES = ("sync", "sync_multi", "async", "async_multi")
SELECT_ROWS = (
    "SELECT device_id, sequence_no, event_time, battery_percent, payload "
    "FROM telemetry_messages ORDER BY sequence_no"
)


def sample_message_thousand() -> list[TelemetryMessage]:
    text = (PROJECT_ROOT / "examples/telemetry/valid.json").read_text(encoding="utf-8")
    sample_message = TelemetryMessage.from_json(text)
    return [
        replace(sample_message, device_id=f"device_{i // 100}", sequence_no=i)
        for i in range(10000)
    ]


def temporary_schema() -> str:
    schema = (PROJECT_ROOT / "sql/001_create_telemetry.sql").read_text(encoding="utf-8")
    return schema.replace(
        "CREATE TABLE telemetry_messages", "CREATE TEMP TABLE telemetry_messages", 1
    )


def make_batches(
    messages: list[TelemetryMessage], batch_size: int
) -> list[list[TelemetryMessage]]:
    if batch_size < 1:
        raise ValueError("batch_size must be at least 1")
    return [
        messages[start : start + batch_size]
        for start in range(0, len(messages), batch_size)
    ]


def verify_saved_rows(
    messages: list[TelemetryMessage],
    inserted_count: int,
    rows: list[tuple[Any, ...]],
) -> None:
    expected = [
        (
            message.device_id,
            message.sequence_no,
            message.event_time,
            message.battery_percent,
            message.to_dict(),
        )
        for message in sorted(messages, key=lambda message: message.sequence_no)
    ]
    assert inserted_count == len(messages), "実挿入件数が入力件数と一致しません"
    assert rows == expected, "DBの行数・順序・保存内容が入力と一致しません"


def benchmark_sync(
    messages: list[TelemetryMessage],
    batch_size: int,
) -> tuple[int, float]:
    batches = make_batches(messages, batch_size)
    schema = temporary_schema()
    with psycopg.connect(
        DSN, autocommit=True, options=CONNECTION_OPTIONS, connect_timeout=5
    ) as conn:
        conn.execute(schema)

        inserted_count = 0
        start = time.perf_counter()
        for batch in batches:
            inserted_count += insert_telemetry_batch(conn, batch)
        elapsed_seconds = time.perf_counter() - start

        # SELECTと内容照合は計測に含めない。
        rows = conn.execute(SELECT_ROWS).fetchall()
        verify_saved_rows(messages, inserted_count, rows)

    return inserted_count, elapsed_seconds


async def benchmark_async(
    messages: list[TelemetryMessage],
    batch_size: int,
) -> tuple[int, float]:
    batches = make_batches(messages, batch_size)
    schema = temporary_schema()
    async with await psycopg.AsyncConnection.connect(
        DSN, autocommit=True, options=CONNECTION_OPTIONS, connect_timeout=5
    ) as conn:
        await conn.execute(schema)

        inserted_count = 0
        start = time.perf_counter()
        for batch in batches:
            inserted_count += await insert_telemetry_batch_async(conn, batch)
        elapsed_seconds = time.perf_counter() - start

        cursor = await conn.execute(SELECT_ROWS)
        rows = await cursor.fetchall()
        verify_saved_rows(messages, inserted_count, rows)

    return inserted_count, elapsed_seconds


def benchmark_sync_multi(
    messages: list[TelemetryMessage],
    batch_size: int,
) -> tuple[int, float]:
    batches = make_batches(messages, batch_size)
    schema = temporary_schema()
    with psycopg.connect(
        DSN, autocommit=True, options=CONNECTION_OPTIONS, connect_timeout=5
    ) as conn:
        conn.execute(schema)

        inserted_count = 0
        start = time.perf_counter()
        for batch in batches:
            inserted_count += insert_telemetry_batch_multi(conn, batch)
        elapsed_seconds = time.perf_counter() - start

        # SELECTと内容照合は計測に含めない。
        rows = conn.execute(SELECT_ROWS).fetchall()
        verify_saved_rows(messages, inserted_count, rows)

    return inserted_count, elapsed_seconds


async def benchmark_async_multi(
    messages: list[TelemetryMessage],
    batch_size: int,
) -> tuple[int, float]:
    batches = make_batches(messages, batch_size)
    schema = temporary_schema()
    async with await psycopg.AsyncConnection.connect(
        DSN, autocommit=True, options=CONNECTION_OPTIONS, connect_timeout=5
    ) as conn:
        await conn.execute(schema)

        inserted_count = 0
        start = time.perf_counter()
        for batch in batches:
            inserted_count += await insert_telemetry_batch_async_multi(conn, batch)
        elapsed_seconds = time.perf_counter() - start

        cursor = await conn.execute(SELECT_ROWS)
        rows = await cursor.fetchall()
        verify_saved_rows(messages, inserted_count, rows)

    return inserted_count, elapsed_seconds


def write_excel_report(
    rows: list[dict[str, str | int | float]], output_file: Path
) -> None:
    """各方式の測定結果を別シートへ保存する。ファイル出力は計測対象外。"""
    workbook = Workbook()
    workbook.remove(workbook.worksheets[0])
    for mode in REPORT_MODES:
        sheet = workbook.create_sheet(mode)
        sheet.append(REPORT_FIELDS)
        for row in rows:
            if row["mode"] == mode:
                sheet.append([row[field] for field in REPORT_FIELDS])
        sheet.freeze_panes = "A2"
        sheet.auto_filter.ref = sheet.dimensions
        for column, field in enumerate(REPORT_FIELDS, start=1):
            sheet.cell(1, column).font = Font(bold=True)
            sheet.column_dimensions[get_column_letter(column)].width = max(
                len(field) + 2, 16
            )
        for cells in sheet.iter_rows(min_row=2, min_col=6, max_col=6):
            cells[0].number_format = "0.000000"

    output_file.parent.mkdir(parents=True, exist_ok=True)
    workbook.save(output_file)
    workbook.close()


def main() -> None:
    messages = sample_message_thousand()
    batch_size = 100
    repeat_count = 5
    durations: dict[str, list[float]] = {mode: [] for mode in REPORT_MODES}
    rows: list[dict[str, str | int | float]] = []

    for run in range(1, repeat_count + 1):
        print(f"比較 {run}/{repeat_count} を開始", flush=True)
        results = {
            "sync": benchmark_sync(messages, batch_size),
            "sync_multi": benchmark_sync_multi(messages, batch_size),
            "async": asyncio.run(benchmark_async(messages, batch_size)),
            "async_multi": asyncio.run(benchmark_async_multi(messages, batch_size)),
        }
        for mode, (inserted_count, elapsed_seconds) in results.items():
            if mode not in durations:
                durations[mode] = []
            durations[mode].append(elapsed_seconds)
            rows.append(
                {
                    "mode": mode,
                    "run": run,
                    "message_count": len(messages),
                    "batch_size": batch_size,
                    "inserted_count": inserted_count,
                    "elapsed_seconds": elapsed_seconds,
                }
            )

    output_file = PROJECT_ROOT / "reports/db_storage_benchmark.csv"
    output_file.parent.mkdir(parents=True, exist_ok=True)
    with output_file.open("w", encoding="utf-8", newline="") as output:
        writer = csv.DictWriter(
            output,
            fieldnames=REPORT_FIELDS,
            lineterminator="\n",
        )
        writer.writeheader()
        writer.writerows(rows)

    excel_file = output_file.with_suffix(".xlsx")
    write_excel_report(rows, excel_file)

    print(
        f"各方式{repeat_count}回、全{len(rows)}回で"
        f"{len(messages)}件の保存内容を確認しました。"
    )
    for mode, values in durations.items():
        print(
            f"{mode}: 最小={min(values):.6f}秒、"
            f"中央値={median(values):.6f}秒、最大={max(values):.6f}秒"
        )
    print("保存先:", output_file)
    print("Excel保存先:", excel_file)
    print(
        "1接続での一括保存の比較です。MQTT通信・接続・DDL・SELECTは計測に含みません。"
    )


if __name__ == "__main__":
    main()
