# TMRP

鉱区の電力設備から送られる遥測データを受信し、PostgreSQLへ保存するシステム。
C++/Qtの模擬設備アプリで、データ送信と遮断器の開閉指令を試験できる。

## 機能

- **受信サーバー**：MQTTの電力データを検証し、機器台帳と照合して保存する。重複を除外し、不正データの拒否理由を記録する。DBへのコミット後にMQTT ACKを返す。
- **運転監視**：受信・保存結果のログ、HTTPヘルスチェック、MQTT再接続、systemd用サービス定義。
- **模擬設備アプリ**：複数設備の追加・設定、周期送信、測定値の変更、開閉指令の受信・応答、設備状態と指令履歴の保存。
- **試験用ツール**：12台の電力計を模擬する継続送信器、指令送信器、受信サーバーの性能測定。
- **分析ツール**：TelemetryのJSON検証、時系列集計・グラフ、低バッテリー判定、CSV／Excel出力。

```text
模擬設備 → Mosquitto → 受信サーバー → PostgreSQL
指令送信スクリプト → Mosquitto → 模擬設備 → 操作結果
```

## 使用技術

| 対象 | 技術 |
|---|---|
| 受信サーバー | Python 3.12以上、Paho MQTT、Psycopg 3、Loguru |
| 通信・DB | MQTT 3.1.1／QoS 1、Mosquitto、PostgreSQL／JSONB |
| 模擬設備 | C++17、Qt 6 Widgets、libmosquitto、SQLite |
| 分析・非同期処理 | NumPy、Pandas、Matplotlib、openpyxl、asyncio、aiomqtt |
| ビルド・検査 | CMake、vcpkg、QtTest、pytest、Ruff、mypy |

## 起動手順

### 1. サーバーの準備（Ubuntu 24.04）

```bash
# Python、PostgreSQL、MQTTと確認用コマンドを導入する
sudo apt update
sudo apt install python3-venv postgresql postgresql-client mosquitto mosquitto-clients git curl

# ソースを取得する（取得済みの場合は既存のTMRPへ移動する）
git clone https://github.com/MudRocksHammer/TMRP.git
cd TMRP

# Python環境を作成し、依存関係を導入する
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'

# PostgreSQLを起動する
sudo systemctl start postgresql

# 現在のOSユーザー用のDBロールと開発DBを作成する（初回のみ）
sudo -u postgres createuser "$(id -un)"
sudo -u postgres createdb --owner="$(id -un)" tmrp_dev
```

既存のDBロール・`tmrp_dev`がある場合は作成を省略する。以降のコマンドはTMRPルートで実行する。

### 2. Brokerと受信サーバーを起動する

端末1：

```bash
# 開発用MQTT Brokerを18884番で起動する
mosquitto -p 18884
```

端末2：

```bash
# ローカルPostgreSQLの接続先を指定する
export TMRP_RECEIVER_DSN="host=/var/run/postgresql dbname=tmrp_dev user=$(id -un)"

# 必要なテーブルを作成し、受信サーバーを起動する
bash scripts/server/start_server.sh --init-db
```

Broker接続先は`examples/power/receiver-local.toml`、設備台帳は`examples/power/assets.json`で設定する。
既定値はBroker `127.0.0.1:18884`、ヘルスチェック `127.0.0.1:8081`。

### 3. データを送信して保存を確認する

端末3：

```bash
# 12台から各1秒に1件ずつ送信する。Ctrl+Cで停止する
.venv/bin/python scripts/mqtt/simulate_power.py --rate-hz 1
```

端末4：

```bash
# 受信サーバーの準備状態と処理件数を確認する
curl --fail http://127.0.0.1:8081/health/ready

# 機器別のDB保存件数を確認する
psql "host=/var/run/postgresql dbname=tmrp_dev user=$(id -un)" \
  -c 'SELECT device_id, count(*) FROM power_telemetry GROUP BY device_id ORDER BY device_id;'
```

GUIから送信・操作する場合は[模擬設備アプリの起動手順](device-simulator/README.md)を使う。
WindowsからUbuntu VMへ接続する方法は[VM接続ガイド](docs/guides/qt-simulator-vm.md)、
systemdでの常駐起動は[サーバー配備手順](docs/guides/power-receiver.md#linuxサーバーへの配備)を参照。
