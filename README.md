# TMRP

鉱区の電力設備から送られる遥測データを受信し、PostgreSQLへ保存するシステム。
C++/Qtの模擬設備アプリで、データ送信と遮断器の開閉指令を試験できる。

## 機能

- **受信サーバー**：MQTTの電力データを検証し、機器台帳と照合して保存する。重複を除外し、不正データの拒否理由を記録する。DBへのコミット後にMQTT ACKを返す。
- **運転監視**：受信・保存結果のログ、HTTPヘルスチェック、MQTT再接続、systemd用サービス定義。
- **HTTPS API**：認証付きの設備一覧・履歴取得、模擬設備への開閉指令、操作結果の照会。
- **監視画面**：C++/Qtで電力状態・配線図を表示。WSSで最新状態と指令結果を受信し、HTTPSで開閉指令を送る。
- **模擬設備アプリ**：複数設備の追加・設定、周期送信、測定値の変更、開閉指令の受信・応答、設備状態と指令履歴の保存。
- **試験用ツール**：12台の電力計を模擬する継続送信器、指令送信器、受信サーバーの性能測定。
- **分析ツール**：TelemetryのJSON検証、時系列集計・グラフ、低バッテリー判定、CSV／Excel出力。

```text
模擬設備 → Mosquitto → 受信サーバー → PostgreSQL
監視画面 ← WSS ← 受信サーバー ← MQTT ← 模擬設備
監視画面 → HTTPS → 受信サーバー → MQTT → 模擬設備 → 操作結果
```

## 使用技術

| 対象 | 技術 |
|---|---|
| 受信サーバー | Python 3.12以上、Paho MQTT、Psycopg 3、Loguru |
| クライアントAPI | FastAPI、Uvicorn、Pydantic、HTTPS／WSS／Bearer認証 |
| 監視画面 | C++17、Qt 6 Widgets／Network／WebSockets |
| 通信・DB | MQTT 3.1.1／QoS 1、Mosquitto、PostgreSQL／JSONB |
| 模擬設備 | C++17、Qt 6 Widgets、libmosquitto、SQLite |
| 分析・非同期処理 | NumPy、Pandas、Matplotlib、openpyxl、asyncio、aiomqtt |
| ビルド・検査 | CMake、vcpkg、QtTest、pytest、Ruff、mypy |

## 初回準備

以下は**Ubuntu VM（192.168.237.128）でサーバー、Windowsで模擬設備と監視画面を動かす**手順。
両方に同じ版のTMRPを用意し、コマンドは各環境のTMRPルートで実行する。

### Ubuntu：依存関係・DB・証明書

```bash
# Python・DB・MQTT・確認用ツールを導入する
sudo apt update
sudo apt install python3-venv postgresql postgresql-client mosquitto mosquitto-clients git curl openssl

# プロジェクトへ移動し、Python環境を準備する
cd ~/pythonLearning/TMRP
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'

# PostgreSQLを起動し、現在のOSユーザー用の開発DBを作成する
# ロールとDBが既にある場合、createuser・createdbは省略する
sudo systemctl start postgresql
sudo -u postgres createuser "$(id -un)"
sudo -u postgres createdb --owner="$(id -un)" tmrp_dev
```

次の設定を済ませてから起動する。既に設定済みなら再作成は不要。

| 準備 | 必要な状態・手順 |
|---|---|
| Mosquitto | 同じBrokerで`127.0.0.1:18884`（VM内の受信サーバー用）と`0.0.0.0:8883`（設備のTLS接続用）を待ち受ける。[TLS接続設定](docs/guides/qt-simulator-vm.md#vmのipへ直接接続する場合)を参照 |
| HTTPS証明書 | `.local/https/server.crt`・`server.key`を配置。証明書のSANに`192.168.237.128`を含める |
| APIトークン | `.local/https/api.env`に`TMRP_API_READ_TOKEN`と`TMRP_API_CONTROL_TOKEN`を保存。[証明書・トークンの準備](docs/guides/https-api.md#起動)を参照 |
| ネットワーク | WindowsからVMの8883/TCP・8443/TCPへ接続可能にする。VMのIPが変わった場合は接続設定と証明書を合わせる |

### Windows：アプリのビルド・CAのコピー

Visual Studio 2022/2026で「C++によるデスクトップ開発」を導入しておく。
通常の64ビットPowerShellで実行する。

```powershell
# Windows側のTMRPへ移動する（保存先が異なる場合は変更する）
Set-Location "$env:USERPROFILE\OneDrive\Documents\TMRP\TMRP"

# 模擬設備をビルドする。Qt・vcpkgも準備する
powershell -NoProfile -ExecutionPolicy Bypass -File .\device-simulator\scripts\setup-windows.ps1

# 監視画面をビルドする。不足しているQt WebSocketsも追加する
powershell -NoProfile -ExecutionPolicy Bypass -File .\monitor-client\scripts\setup-windows.ps1

# サーバー証明書の検証用CAをVMからコピーする
New-Item -ItemType Directory -Force "$env:USERPROFILE\tmrp-certs" | Out-Null
scp shou@192.168.237.128:/home/shou/tmrp-mqtt-tls/ca.crt "$env:USERPROFILE\tmrp-certs\ca.crt"
```

以降のWindows起動例はVS2026用。VS2022の場合はパス中の`build-windows-vs2026`を`build-windows`に置き換える。
Linuxでアプリを動かす場合のビルド手順は[模擬設備](device-simulator/README.md#linuxubuntu-2404)と[監視画面](monitor-client/README.md#linuxでビルド起動)を参照。

## 起動手順

**① PostgreSQL・Mosquitto → ② 受信サーバー → ③ 模擬設備の送信 → ④ 監視画面 → ⑤ 操作確認**の順に進める。

| 実行場所 | 用途 | 開いたままにするか |
|---|---|---|
| Ubuntu・端末A | 受信サーバー | はい。Ctrl+Cで停止する |
| Ubuntu・端末B | 稼働状態・DB保存の確認 | 確認時のみ |
| Windows・PowerShell | 模擬設備と監視画面の起動 | 起動後は各アプリを開いたままにする |

### 1. PostgreSQL・Mosquittoを起動する（Ubuntu・端末A）

```bash
# プロジェクトへ移動し、DBと設定済みBrokerを起動する
cd ~/pythonLearning/TMRP
sudo systemctl start postgresql mosquitto

# MQTTの待受ポートを確認する
ss -ltn | grep -E ':(18884|8883)\b'
```

`127.0.0.1:18884`と`0.0.0.0:8883`が表示されることを確認する。
Mosquittoの設定を変更した直後は`sudo systemctl restart mosquitto`で反映する。
この構成では別途`mosquitto -p 18884`を起動しない。

### 2. HTTPS/WSS付き受信サーバーを起動する（Ubuntu・端末A）

同じ受信サーバーが既に動いている場合は、先にそのプロセスまたはsystemdサービスを停止する。

```bash
# 保存済みトークンを、この端末から起動するサーバーへ渡す
set -a
source .local/https/api.env
set +a

# PostgreSQL接続先を指定する
export TMRP_RECEIVER_DSN="host=/var/run/postgresql dbname=tmrp_dev user=$(id -un)"

# 必要なテーブル・索引を作成し、HTTPS/WSS付きで起動する
bash scripts/server/start_server.sh --https --init-db
```

`--init-db`は既存データを消さない。設定は`examples/power/receiver-https.toml`を使用する。
`--https`を省略すると既定ではMQTT受信のみになり、監視画面から接続できない。
`monitor_gateway`は起動不要。

Ubuntuの**端末B**で準備完了を確認する。

```bash
# MQTT購読とDB接続が準備できているか確認する
curl --fail http://127.0.0.1:8081/health/ready
```

`"ready": true`になってから次へ進む。端末Aは開いたままにする。

### 3. 模擬設備を起動し、送信を開始する（Windows）

```powershell
# ビルド済みの模擬設備アプリを起動する
Start-Process .\device-simulator\build-windows-vs2026\Release\tmrp-device-simulator.exe
```

「設備を追加」または「設定を編集」で、まず1台を次のように設定する。

| 項目 | 設定値 |
|---|---|
| 機器ID／設備ID | `power-meter-001`／`breaker-001` |
| Broker IP／ポート | `192.168.237.128`／`8883` |
| TLS | オン |
| CAファイル | `C:\Users\xiaor\tmrp-certs\ca.crt`（実際のユーザー名に合わせる） |
| ユーザー名・パスワード | Mosquittoに登録したMQTT接続用の資格情報 |
| 送信元IP | 空欄 |
| 送信頻度 | 1 Hz |

「全設備を接続」→「全設備の定期送信」を押す。
個別操作なら設備詳細の「接続」→「定期送信を開始」を使う。
開閉試験を行う設備では「遠方操作を許可」をオンにし、インターロック条件を確認する。

2台目は`power-meter-002`／`breaker-002`にする。機器ID・設備IDはサーバー設定と監視図の対応を一致させる。
MQTTパスワードは設定JSONに保存されないため、次回起動時も入力する。

### 4. 監視画面を起動して接続する（Windows）

同じPowerShellで実行する。APIトークンはUbuntuの`.local/https/api.env`にある値を使う。
**MQTTのユーザー名・パスワードとは別**で、入力するのは`TMRP_API_CONTROL_TOKEN=`より後ろの値だけ。

```powershell
# CAの場所と操作用トークンを監視画面へ渡す
$env:TMRP_MONITOR_CA_FILE = "$env:USERPROFILE\tmrp-certs\ca.crt"
$env:TMRP_API_CONTROL_TOKEN = Read-Host 'TMRP_API_CONTROL_TOKEN'

# ビルド済みの監視画面を起動する
Start-Process .\monitor-client\build-windows-vs2026\Release\tmrp-monitor-client.exe
```

画面のサーバー欄に`https://192.168.237.128:8443`を入力し、「连接服务器」を押す。
設備001がオンラインになり、電圧・電流・電力・遮断器状態が表示されることを確認する。
監視画面への配信は通常1秒周期。設備の送信を止めると約10秒後にオフラインになる。

### 5. 保存・操作・結果通知を確認する

Ubuntuの**端末B**で保存を確認する。

```bash
# 設備ごとの保存件数を確認する。時間を置いて再実行し、増加を確認する
psql "host=/var/run/postgresql dbname=tmrp_dev user=$(id -un)" \
  -c 'SELECT device_id, count(*) FROM power_telemetry GROUP BY device_id ORDER BY device_id;'
```

Windowsの監視画面で次の順に操作する。

1. ライン図の編集モードを終了し、オンラインの設備001を右クリックする。
2. 「分闸」（開放）を選択し、対象を確認して送信する。
3. 模擬設備の「受信指令・操作結果」に指令が表示され、遮断器が開くことを確認する。
4. 監視画面の操作記録が「执行完成」になり、テレメトリーの遮断器表示も開放へ変わることを確認する。
5. 「合闸」（投入）でも同様に確認する。

これで**送信 → DB保存 → 監視表示 → 指令送信 → 設備操作 → 結果通知**の往復を確認できる。
`simulate_power.py`はテレメトリー送信専用なので、この開閉試験ではQt模擬設備を使用する。
同じ機器IDで両方の送信器を同時に動かさない。

### 停止する順番

1. 操作中の指令の結果を確認してから、監視画面を切断・終了する。
2. 模擬設備で「全定期送信を停止」→「全設備を切断」を押し、終了する。
3. Ubuntuの端末AでCtrl+Cを押し、受信サーバーを終了する。

PostgreSQL・Mosquittoは次回用に起動したままでよい。
常駐運用への切替は[systemd配備手順](docs/guides/power-receiver.md#linuxサーバーへの配備)を参照。
