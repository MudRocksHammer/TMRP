# Telemetry分析の再現手順

2デバイス・合計12件の学習用TelemetryをNumPyとPandasで分析する。
バッテリーの基本統計と欠損値の扱いを確認し、NotebookとCSVに結果を残す。

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
`analysis`にはNumPy、Pandas、JupyterLab、ipykernel、nbconvertが含まれる。

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
- 最後のコードセルで`reports/jupyter_battery_summary.csv`を保存する。

### 欠損処理の比較

| device_id | np.mean | np.nanmean | 欠損を0に置き換えた平均 |
| --------- | ------- | ---------: | ----------------------: |
| robot-001 | NaN     |       95.2 |                 約79.33 |
| robot-002 | NaN     |       75.6 |                    63.0 |

今回の配列では`np.mean`は欠損を含むためNaNになる。
`np.nanmean`とPandasの既定の`mean()`は欠損を除外する。
未計測を残量0として扱うと平均を過小評価するため、今回の集計では0で補わない。
実際に測定された0は有効な値であり、欠損とは区別する。

## 生成物

| パス                                  | 作成する処理         | 内容                                       |
| ------------------------------------- | -------------------- | ------------------------------------------ |
| `examples/telemetry/analysis.jsonl`   | データ生成スクリプト | 入力用の12件のTelemetry                    |
| `reports/battery_summary.csv`         | 分析スクリプト       | デバイス別の件数・平均・最小・最大・欠損数 |
| `reports/jupyter_battery_summary.csv` | Notebook             | デバイス別の欠損数と3通りの平均の比較      |

CSVはどちらもUTF-8、DataFrameの行番号なしで保存する。出力ディレクトリは自動作成し、同名ファイルは上書きする。
NotebookのCSVの`mean`列はNaNのため空欄になる。`nanmean`列に採用した欠損除外平均を記録する。

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
元のNotebookは上書きしないが、セル内のCSV保存は実行されるため、`reports/jupyter_battery_summary.csv`は更新される。

既存の`scripts/check_test.sh`は書式を自動修正し、Ruffの対象は`src`と`tests`のみ。
分析スクリプトとNotebookのチェックには上記コマンドを使う。
pytestとmypyだけではNotebookの実行を検証できないため、全セルの再実行も確認する。
