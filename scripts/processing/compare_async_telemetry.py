import asyncio
import csv
import time
from pathlib import Path
from statistics import median

from myproj.alerts.battery import BatteryAlertEvent, BatteryAlertMonitor
from myproj.processing.async_pipeline import run_pipeline
from myproj.telemetry.models import TelemetryMessage
from myproj.telemetry.stream import iter_telemetry


def process_sync(
    messages: list[TelemetryMessage],
    delay: float,
) -> list[BatteryAlertEvent]:
    monitor = BatteryAlertMonitor()

    events: list[BatteryAlertEvent] = []
    for message in messages:
        time.sleep(delay)
        event = monitor.process(message)
        if event is not None:
            events.append(event)
    return events


async def process_async(
    messages: list[TelemetryMessage],
    delay: float,
) -> list[BatteryAlertEvent]:
    monitor = BatteryAlertMonitor()

    events: list[BatteryAlertEvent] = []

    for message in messages:
        await asyncio.sleep(delay)
        event = monitor.process(message)
        if event is not None:
            events.append(event)
    return events


async def run_async(
    groups: dict[str, list[TelemetryMessage]],
    delay: float,
) -> list[BatteryAlertEvent]:
    results = await asyncio.gather(
        # デバイスごとのコルーチンを個別の引数として渡す
        *(process_async(messages, delay) for messages in groups.values())
    )
    # デバイスごとのイベントを1つのリストにまとめる
    return [event for sublist in results for event in sublist]


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def main() -> None:
    input_file = PROJECT_ROOT / "examples/telemetry/battery_alerts.jsonl"
    with input_file.open(encoding="utf-8") as source:
        messages = list(iter_telemetry(source))

    groups: dict[str, list[TelemetryMessage]] = {}
    for message in messages:
        groups.setdefault(message.device_id, []).append(message)

    delay = 0.05
    repeat_count = 5
    durations: dict[str, list[float]] = {"sync": [], "gather": [], "queue": []}
    rows: list[dict[str, str | int | float]] = []

    for run in range(1, repeat_count + 1):
        # 各方式の呼び出しを独立して計測する。
        start = time.perf_counter()
        sync_results = [
            process_sync(device_messages, delay) for device_messages in groups.values()
        ]
        sync_seconds = time.perf_counter() - start

        # 非同期版はイベントループの生成・終了も計測に含める。
        start = time.perf_counter()
        gather_results = asyncio.run(run_async(groups, delay))
        gather_seconds = time.perf_counter() - start

        start = time.perf_counter()
        queue_results = asyncio.run(run_pipeline(groups, delay))
        queue_seconds = time.perf_counter() - start

        # 比較と記録は計測後に行う。同期版だけが入れ子の戻り値になる。
        sync_events = [event for events in sync_results for event in events]
        expected = sorted(
            sync_events, key=lambda event: (event.device_id, event.sequence_no)
        )
        results = {
            "sync": (sync_events, sync_seconds),
            "gather": (gather_results, gather_seconds),
            "queue": (queue_results, queue_seconds),
        }
        for mode, (events, elapsed_seconds) in results.items():
            actual = sorted(
                events, key=lambda event: (event.device_id, event.sequence_no)
            )
            assert actual == expected, f"{mode}の{run}回目でイベントが一致しません"
            assert len(events) == 5, f"{mode}の{run}回目のイベント数が5件ではありません"

            durations[mode].append(elapsed_seconds)
            rows.append(
                {
                    "mode": mode,
                    "run": run,
                    "device_count": len(groups),
                    "message_count": len(messages),
                    "delay_seconds": delay,
                    "event_count": len(events),
                    "elapsed_seconds": elapsed_seconds,
                }
            )

    # 全15回の検証に成功してから、レポートを上書き保存する。
    output_file = PROJECT_ROOT / "reports/async_benchmark.csv"
    output_file.parent.mkdir(parents=True, exist_ok=True)
    with output_file.open("w", encoding="utf-8", newline="") as output:
        writer = csv.DictWriter(
            output,
            fieldnames=[
                "mode",
                "run",
                "device_count",
                "message_count",
                "delay_seconds",
                "event_count",
                "elapsed_seconds",
            ],
        )
        writer.writeheader()
        writer.writerows(rows)

    print(f"各方式{repeat_count}回、全15回で同じ5件のイベントを確認しました。")
    for mode, values in durations.items():
        print(f"{mode}: 最小={min(values):.3f}秒、中央値={median(values):.3f}秒")
    print("保存先:", output_file)
    print("模擬受信待ちの比較です。MQTT・DBの実測は含みません。")


if __name__ == "__main__":
    main()
