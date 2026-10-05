from pathlib import Path

import numpy as np
import pandas as pd

from myproj.stream import iter_telemetry


def main() -> None:
    project_root = Path(__file__).resolve().parents[1]
    input_path = project_root / "examples/telemetry/analysis.jsonl"

    with input_path.open(encoding="utf-8") as source:
        rows = [message.to_dict() for message in iter_telemetry(source)]

    df = pd.DataFrame(rows)
    df["event_time"] = pd.to_datetime(df["event_time"], utc=True)

    # print(df)

    # df.head()

    # print(df.describe())
    # print(df.shape)
    # print(df.size)
    # print(df["device_id"].nunique())

    # print(df.head())
    # print(df.dtypes)
    # print(df.T)
    # print(df.iloc[:, 2].iloc[-5:])
    # print(df["battery_percent"].isna().sum())
    # print(df[df["battery_percent"].isna()])

    # maximum battery percent
    # print(df["battery_percent"].max())
    # minimum battery percent
    # print(df["battery_percent"].min())
    # average battery percent
    # print(df["battery_percent"].mean())
    # median battery percent
    # print(df["battery_percent"].median())

    # 欠損は未計測ので０で補わず、平均は測定値のある行だけで計算する
    summary = df.groupby("device_id").agg(
        message_count=("battery_percent", "size"),
        battery_count=("battery_percent", "count"),
        battery_mean=("battery_percent", "mean"),
        battery_min=("battery_percent", "min"),
        battery_max=("battery_percent", "max"),
    )
    # print(summary)

    summary["battery_missing"] = summary["message_count"] - summary["battery_count"]

    # print(summary)

    report = summary.reset_index()

    output_path = project_root / "reports/battery_summary.csv"
    output_path.parent.mkdir(parents=True, exist_ok=True)

    report.to_csv(output_path, index=False, encoding="utf-8")

    loaded = pd.read_csv(output_path, encoding="utf-8")

    print(loaded.to_string(index=False))
    print("保存先：", output_path)

    for device_id, group in df.groupby("device_id"):
        values = group["battery_percent"].to_numpy(dtype=float, copy=True)

        print("デバイス", device_id)
        print("配列:", values)

        print("欠損数:", np.isnan(values).sum())
        print("通常の平均:", np.mean(values))
        print("欠損をのぞいて平均:", np.nanmean(values))
        print("欠損を０にした平均:", np.mean(np.nan_to_num(values, nan=0.0)))

    sample = np.array([0.0, 100.0, np.nan])
    print("0を含めて有効な測定値の平均:", np.nanmean(sample))


if __name__ == "__main__":
    main()
