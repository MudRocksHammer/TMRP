# プロジェクト構成

本体とテストは機能別、スクリプトは用途別、文書は読む目的別に配置する。
実行コマンドは、特に指定がなければTMRPのルートから実行する。

## 本体: src/myproj

| フォルダー | 責務 | ファイル |
|---|---|---|
| app | CLI、アプリケーション設定、ログ設定 | cli.py、config.py、logging_config.py |
| telemetry | Telemetryの型・検証・JSON変換とJSONL読み込み | models.py、stream.py |
| collection | MQTT入力の検証、同期／非同期の収集処理 | mqtt_validation.py、collector.py、async_collector.py、async_mqtt.py |
| persistence | PostgreSQLへの同期／非同期保存 | storage.py、async_storage.py |
| alerts | バッテリーの状態遷移とデバイス別Monitor | battery.py |
| processing | producer・Queue・アラート判定の非同期処理 | async_pipeline.py |

各フォルダーに__init__.pyを置き、Pythonパッケージとして扱う。
ルートのmyproj/__init__.pyはパッケージの入口として残す。
内部importは機能フォルダーまで指定する。

```python
from myproj.telemetry.models import TelemetryMessage
from myproj.persistence.async_storage import insert_telemetry_batch_async
from myproj.collection.async_collector import run_db_pipeline
from myproj.alerts.battery import BatteryAlertMonitor
```

CLIの登録先はpyproject.tomlの`myproj.app.cli:main`。
既存の仮想環境でも、配置変更後は編集可能インストールを更新する。

```bash
# CLIの登録先とパッケージ情報を更新する（既存の依存関係を利用する）
.venv/bin/python -m pip install --no-deps --no-build-isolation -e .

# CLIが新しい配置で起動することを確認する
.venv/bin/tmrp --version
```

新規環境では[READMEのSetup](../../README.md#setup)に従って依存関係も導入する。

## テスト: tests

最初に単体／結合を分け、その下を本体に対応した機能別にする。

```text
tests/
├── conftest.py                 # 全体で共有するLoguru・正常Telemetry用fixture
├── units/
│   ├── app/                    # CLI・設定・ログ
│   ├── telemetry/              # モデル・JSON変換・JSONL
│   ├── collection/             # MQTT検証・collector・キャンセル
│   ├── alerts/                 # 状態遷移・Monitor
│   ├── processing/             # Queueパイプライン
│   └── smoke/                  # 学習初期の最小テスト
└── integration/
    ├── conftest.py             # DB接続・接続先・一時テーブル定義
    ├── persistence/            # 同期／非同期のDB保存
    ├── collection/             # collectorと実DB
    └── alerts/                 # CSVレポートの入出力
```

integration/conftest.pyのfixtureは配下のテストで共有する。
結合テストでもCSV出力の検証にはDB接続は不要。
単体と結合で同名テストモジュールを作らず、collectorの結合テストには
`_integration.py`を付ける。新しいテストを追加するときもこの規則に従う。

```bash
# 非同期collectorの単体テストを実行する
.venv/bin/python -m pytest -q tests/units/collection/test_async_collector.py

# 全ファイルの整形・lint・本体の型検査・DBを含む全テストを実行する
bash scripts/dev/check_test.sh --db
```

## スクリプト: scripts

| フォルダー | スクリプト |
|---|---|
| dev | check_test.sh: 開発時の品質チェック |
| telemetry | generate_sample_telemetry.py: 学習用JSONL生成 |
| analysis | analyze_sample_telemetry.py、report_battery_alerts.py: 分析・CSV出力 |
| mqtt | publish_telemetry.py、subscribe_telemetry.py、subscribe_telemetry_async.py: MQTT送受信 |
| persistence | store_sample_telemetry.py: DB保存の実行例 |
| processing | compare_async_telemetry.py: 同期・非同期・Queueの比較 |

例: `bash scripts/dev/check_test.sh`、
`.venv/bin/python scripts/analysis/report_battery_alerts.py`。
サンプルデータを扱うPythonスクリプトは自身の配置からルートを解決し、examplesとreportsを参照する。
check_test.shも自身の配置からルートへ移動して検査を実行する。

## 文書: docs

- development: セットアップ後の検証と、開発時に参照する構成案内。
- reference: データ契約・設定などの仕様。
- guides: MQTT・DB・分析・アラート・非同期処理の利用手順。

入口は[文書一覧](../README.md)。READMEには概要と主要な手順へのリンクを置く。
examples、reports、notebooks、sqlは従来の役割と配置を維持する。
Notebook内のimportも本体の新しいパッケージ構成に合わせる。
