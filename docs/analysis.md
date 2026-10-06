# Telemetry分析の再現手順

2デバイス・合計12件の学習用TelemetryをNumPyとPandasで分析する。
バッテリーの基本統計と欠損値の扱いを確認し、NotebookとCSVに結果を残す。
さらにMatplotlibで推移を可視化し、3分・日次の集計とUTC／日本時間の日付境界を比較する。

## 環境の準備

Python 3.12以降を使用する。以下のコマンドはすべてTMRPのルートディレクトリで実行する。
まだリポジトリを取得していない場合は、[READMEのSetup](../README.md#setup)を先に参照する。

```bash
# .venvがない場合だけ、プロジェクト専用の仮想環境を作成する
python3 -m venv .venv

# 本体、開発ツール、分析・Notebook用の依存関係をインストールする
.venv/bin/python -m pip install -e ".[dev,analysis]"
```

既存の`.venv`があれば作成コマンドは省略する。以降は`.venv/bin/`のコマンドを直接使うため、activateは不要。
`analysis`にはNumPy、Pandas、Matplotlib、JupyterLab、ipykernel、nbconvertが含まれる。

## 1. 学習データを生成する

```bash
# 固定の測定値から12件のJSON Linesを生成する
.venv/bin/python scripts/generate_sample_telemetry.py
```

出力先は`examples/telemetry/analysis.jsonl`。繰り返し実行すると同じ内容で上書きし、件数は増えない。
各デバイスの連番は1〜6、測定時刻は2026-10-01の00:00〜00:05（UTC、1分間隔）。

| デバイス  | battery_percent（時刻順） |
| --------- | ------------------------- |
| robot-001 | 100, 98, 96, null, 92, 90 |
| robot-002 | 80, 78, 76, 74, null, 70  |

`null`は未計測を表す。今回はbattery_percentを分析対象とする。

## 2. スクリプトで集計する

```bash
# 入力検証、DataFrameへの変換、デバイス別集計、CSV保存を実行する
.venv/bin/python scripts/analyze_sample_telemetry.py
```

`iter_telemetry`で入力を検証した後、DataFrameへ変換する。
`event_time`をUTCの日時型へ変換し、デバイス別の件数と基本統計を求める。
結果は画面と`reports/battery_summary.csv`へ出力する。

| device_id | message_count | battery_count | battery_mean | battery_min | battery_max | battery_missing |
| --------- | ------------: | ------------: | -----------: | ----------: | ----------: | --------------: |
| robot-001 |             6 |             5 |         95.2 |          90 |         100 |               1 |
| robot-002 |             6 |             5 |         75.6 |          70 |          80 |               1 |

`message_count`は欠損を含む全件数（`size`）、`battery_count`は有効な測定値の件数（`count`）。
両者の差が欠損数になる。平均・最小・最大の計算では欠損を除外する。

## 3. Notebookで分析を再現する

```bash
# 仮想環境のPythonをJupyterのカーネルとして登録する
.venv/bin/python -m ipykernel install --prefix "$PWD/.venv" --name tmrp --display-name "Python (TMRP)"

# ブラウザを自動起動せず、JupyterLabを開始する
.venv/bin/jupyter lab --no-browser
```

1. 端末に表示されるURLをブラウザで開く。
2. `notebooks/telemetry_analysis.ipynb`を開き、カーネルに`Python (TMRP)`を選択する。
3. **Kernel → Restart Kernel and Run All Cells**で、変数を初期化して全セルを順番に実行する。
4. エラーがなく、以下の期待結果と一致することを確認して保存する。

Notebookのパス解決は、作業ディレクトリがTMRPのルートまたは`notebooks/`であることを前提とする。
通常は上記の起動・ファイル選択でこの条件を満たす。

- DataFrameの形状: `(12, 9)`。
- バッテリー欠損数: 全体で2件、各デバイス1件。
- デバイス別の平均: 95.2と75.6。
- 全体の有効値10件の平均: 85.4、中央値: 85.0。
- 欠損処理の比較を`reports/jupyter_battery_summary.csv`へ保存する。
- 続くセルでグラフ、3分集計、日次集計を生成し、最後にタイムゾーンを比較する。

### 欠損処理の比較

| device_id | np.mean | np.nanmean | 欠損を0に置き換えた平均 |
| --------- | ------- | ---------: | ----------------------: |
| robot-001 | NaN     |       95.2 |                 約79.33 |
| robot-002 | NaN     |       75.6 |                    63.0 |

今回の配列では`np.mean`は欠損を含むためNaNになる。
`np.nanmean`とPandasの既定の`mean()`は欠損を除外する。
未計測を残量0として扱うと平均を過小評価するため、今回の集計では0で補わない。
実際に測定された0は有効な値であり、欠損とは区別する。

## 4. バッテリー推移のグラフ

Notebookの描画セルは、デバイスごとに`event_time`を昇順に並べ、同じ図へ折れ線と丸いマーカーを描く。
横軸はUTCの測定時刻、縦軸はバッテリー残量（%、0〜100）。凡例でデバイスを区別する。
画像は`reports/figures/telemetry_data_by_device.png`へ保存する。

- robot-001の00:03、robot-002の00:04は欠損なので、点が描かれず、その前後の線が途切れる。
- robot-002の00:05・70%は直前が欠損のため孤立した点になる。丸いマーカーによって、この有効値も確認できる。
- 欠損行の削除や0による補完は行わず、未計測の状態を図に残す。

## 5. 3分ごとの集計

Notebookで`event_time`を日時インデックスにし、時刻順へ並べる。
デバイス別に`resample("3min", closed="left", label="left")`で集計する。
区間は開始時刻を含み、終了時刻を含まない。結果の`event_time`は区間の開始を表す。

例: 00:00の行は00:00以上〜00:03未満、00:03の行は00:03以上〜00:06未満。
`reports/battery_3min_summary.csv`の期待結果は次の4行。日付はすべて2026-10-01、時刻はUTC。

| device_id | event_time（時刻部分） | message_count | battery_count | battery_mean | battery_missing |
|---|---|---:|---:|---:|---:|
| robot-001 | 00:00 | 3 | 3 | 98.0 | 0 |
| robot-001 | 00:03 | 3 | 2 | 91.0 | 1 |
| robot-002 | 00:00 | 3 | 3 | 78.0 | 0 |
| robot-002 | 00:03 | 3 | 2 | 72.0 | 1 |

robot-001の後半はNaN・92・90なので、有効値2件を使い、平均は`(92 + 90) / 2 = 91`になる。

## 6. UTCの日次レポート

同じ日時インデックスから、デバイス別に`resample("1D", closed="left", label="left")`で集計する。
`reports/battery_1d_summary.csv`には、日付を識別する`event_time`も残す。
現在の2行はいずれも`2026-10-01 00:00:00+00:00`で、UTCの同日の集計を表す。

| device_id | message_count | battery_count | battery_mean | battery_min | battery_max | battery_missing | battery_missing_rate |
|---|---:|---:|---:|---:|---:|---:|---:|
| robot-001 | 6 | 5 | 95.2 | 90 | 100 | 1 | 約0.1667 |
| robot-002 | 6 | 5 | 75.6 | 70 | 80 | 1 | 約0.1667 |

`battery_missing_rate = battery_missing / message_count`。CSVには丸めず0〜1の比率で保存する。
1/6（約0.1667）は約16.7%に相当する。

このレポートは当日の00:00〜00:05の学習サンプルに基づく。
欠損率は記録内のバッテリー未計測率であり、通信のオンライン率や24時間全体の観測状況を表すものではない。
今回のデータでは各デバイスの集計区間に必ず記録がある。記録0件の日や通信途絶の扱いは、この課題では検証していない。

## 7. UTCと日本時間の日付境界

最後のコードセルでは、元の12件とは別の比較用DataFrameを作る。
同一デバイスの測定値として、UTCの2026-10-01 14:59に90%、15:00に70%を設定する。
`boundary_df`をUTCで日次集計した結果と、`tz_convert("Asia/Tokyo")`の後で日次集計した結果を表示する。
この比較はNotebook内で行い、既存のレポートCSVには混ぜない。

| 集計基準 | 日付 | count | mean |
|---|---|---:|---:|
| UTC | 2026-10-01 | 2 | 80.0 |
| 日本時間 | 2026-10-01 | 1 | 90.0 |
| 日本時間 | 2026-10-02 | 1 | 70.0 |

UTCの14:59・15:00は、日本時間では23:59・翌日00:00になる。
`tz_convert`で表す瞬間は変わらないが、現地の日付が変わるため集計結果は異なる。
日本時間の日次レポートでは、日付の区切りを決める前にタイムゾーンを変換する。
集計後に時刻表示だけを変えても、すでにまとめた測定値を別の日へ分け直すことはできない。

## 生成物

| パス                                  | 作成する処理         | 内容                                       |
| ------------------------------------- | -------------------- | ------------------------------------------ |
| `examples/telemetry/analysis.jsonl`   | データ生成スクリプト | 入力用の12件のTelemetry                    |
| `reports/battery_summary.csv`         | 分析スクリプト       | デバイス別の件数・平均・最小・最大・欠損数 |
| `reports/jupyter_battery_summary.csv` | Notebook             | デバイス別の欠損数と3通りの平均の比較      |
| `reports/figures/telemetry_data_by_device.png` | Notebook | 欠損と測定点を示すバッテリー推移のグラフ |
| `reports/battery_3min_summary.csv` | Notebook | デバイス別・3分単位の件数、平均、欠損数 |
| `reports/battery_1d_summary.csv` | Notebook | デバイス別・UTC日次の基本統計と欠損率 |

CSVはすべてUTF-8、DataFrameの行番号なしで保存する。出力ディレクトリは自動作成し、同名ファイルは上書きする。
`jupyter_battery_summary.csv`の`mean`列はNaNのため空欄になる。`nanmean`列に採用した欠損除外平均を記録する。

## 品質チェックと画面を使わない再実行

```bash
# 本体・テスト・スクリプト・Notebookのコード規約を、自動修正せず検査する
.venv/bin/python -m ruff check src tests scripts notebooks

# 同じ対象の書式を、自動修正せず検査する
.venv/bin/python -m ruff format --check src tests scripts notebooks

# src内のコードをstrict設定で型検査する
.venv/bin/python -m mypy

# 既存の単体テストを実行する
.venv/bin/python -m pytest -q

# 再実行したNotebookを置く一時ディレクトリを作成する
analysis_run_dir=$(mktemp -d /tmp/tmrp-analysis-XXXXXX)

# 新しいカーネルで全セルを実行し、実行済みのコピーを一時ディレクトリへ保存する
.venv/bin/python -m jupyter nbconvert --to notebook --execute notebooks/telemetry_analysis.ipynb --ExecutePreprocessor.kernel_name=tmrp --output telemetry_analysis.executed --output-dir "$analysis_run_dir"
```

画面を使わない実行も、先にデータ生成と`tmrp`カーネルの登録を行う。
元のNotebookは上書きしないが、セル内の保存処理は実行されるため、以下の生成物は更新される。

- `reports/jupyter_battery_summary.csv`
- `reports/figures/telemetry_data_by_device.png`
- `reports/battery_3min_summary.csv`
- `reports/battery_1d_summary.csv`

`reports/battery_summary.csv`は分析スクリプトの出力なので、Notebookだけの再実行では更新されない。
再実行したNotebookを開き、グラフと上記の期待結果を確認する。元のNotebookに出力を保存する場合は、JupyterLab側でも全セルを実行して保存する。

既存の`scripts/check_test.sh`は書式を自動修正し、Ruffの対象は`src`と`tests`のみ。
分析スクリプトとNotebookのチェックには上記コマンドを使う。
pytestとmypyだけではNotebookの実行を検証できないため、全セルの再実行も確認する。
