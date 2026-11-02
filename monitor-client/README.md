# TMRP 電力監視クライアント

C++17 / Qt 6 WidgetsのWindows・Linux用監視画面。
受信サーバーのWSSから設備状態を受け取り、HTTPSで模擬設備への開閉指令を登録する。

- 電圧・電流・電力・周波数、遮断器状態、直近60サンプルの電力推移を表示。
- 設備の配置・接続線を編集し、JSONで保存・読込。
- 指令の受付・完了・拒否・失敗・結果不明を表示。遮断器の表示はテレメトリーに従う。
- 通信断・古いデータではオフライン表示。自動再接続するが、新しい指令は自動生成しない。

```text
Qt模擬設備 ─ MQTT ─ 受信サーバー ─ PostgreSQL
                        │
                        ├ WSS :8443 ─ 状態・指令結果 → 監視画面
                        └ HTTPS :8443 ← 操作指令 ─── 監視画面
```

## サーバー起動（Ubuntu）

初回は[HTTPS設定](../docs/guides/https-api.md)で証明書・トークン・DBを準備する。
既存の受信サーバーを停止し、TMRPルートで実行する。`monitor_gateway`は起動しない。

```bash
# WSSを含むPython依存関係を更新する
.venv/bin/python -m pip install -e '.[dev]'

# 保存済みAPIトークンを環境変数へ読み込む
set -a
source .local/https/api.env
set +a

# DB接続先を指定してHTTPS/WSS付き受信サーバーを起動する
export TMRP_RECEIVER_DSN="host=/var/run/postgresql dbname=tmrp_dev user=$(id -un)"
bash scripts/server/start_server.sh --https --init-db
```

Brokerは同じMosquittoの`127.0.0.1:18884`（サーバー内）と`192.168.237.128:8883`（設備のTLS接続）を使う。
APIは`8443`、ローカルヘルスチェックは`8081`。VMのファイアウォールでは接続元から8443/TCPを許可する。

## Windowsでビルド・起動

Visual Studio 2022/2026の「C++によるデスクトップ開発」が必要。
セットアップは模擬設備と共通のQtを使用し、不足しているQt WebSocketsを追加する。
通常の64ビットPowerShellからTMRPルートで実行する。

```powershell
# 依存関係の準備、ビルド、テスト、Qt DLL配置を実行する
powershell -ExecutionPolicy Bypass -File .\monitor-client\scripts\setup-windows.ps1

# サーバー証明書を検証するCAファイルと操作用APIトークンを設定する
$env:TMRP_MONITOR_CA_FILE = "$env:USERPROFILE\tmrp-certs\ca.crt"
$env:TMRP_API_CONTROL_TOKEN = Read-Host 'TMRP_API_CONTROL_TOKEN'

# 再ビルド・テスト後に監視画面を起動する
powershell -ExecutionPolicy Bypass -File .\monitor-client\scripts\build-windows.ps1 -Launch
```

既存Qtを指定する場合はセットアップに`-QtPrefix 'C:\Qt\6.8.3\msvc2022_64'`を付ける。
VS2026の実行ファイルは`monitor-client\build-windows-vs2026\Release\tmrp-monitor-client.exe`。
読み取り専用で使う場合は操作用環境変数を設定せず、`TMRP_API_READ_TOKEN`を設定する。
CAをOSで信頼済みなら`TMRP_MONITOR_CA_FILE`は不要。証明書検証の無効化はしない。

## Linuxでビルド・起動

```bash
# Qt、WebSockets、コンパイラーを導入する
sudo apt install cmake g++ qt6-base-dev qt6-websockets-dev

# 監視クライアントをビルド・テストする
cmake -S monitor-client -B monitor-client/build
cmake --build monitor-client/build --parallel 2
ctest --test-dir monitor-client/build --output-on-failure

# CAとAPIトークンを読み込み、監視画面を起動する
export TMRP_MONITOR_CA_FILE="$HOME/tmrp-mqtt-tls/ca.crt"
set -a
source .local/https/api.env
set +a
monitor-client/build/tmrp-monitor-client
```

## 接続・操作

1. 模擬設備をBrokerへ接続し、周期送信を開始する。
2. 監視画面に`https://192.168.237.128:8443`とAPIトークンを入力し、接続する。
3. 設備ID・遮断器IDを`examples/power/receiver-https.toml`の`api_command_targets`と合わせる。
4. 運転モードでオンライン設備を右クリックして開放・投入を選び、対象を確認して送信する。

APIトークンはMQTTのユーザー名・パスワードとは別。画面はトークンを保存しない。
初期の図は`power-meter-001/002`と`breaker-001/002`。操作は模擬設備の遠方モード・インターロック条件にも従う。

## 通信仕様

- `WSS /api/stream`：Bearer認証。DBコミット済みの最新状態と最近500件の指令結果を、通常1秒周期で完全スナップショットとして配信する。全サンプル配信ではなく、詳細履歴はHTTPS APIから取得する。
- 最新データの受信から10秒経過、観測時刻のずれ15秒以上、またはMQTT未準備で設備をオフラインにする。監視画面でも5秒間スナップショットが届かなければ操作を禁止する。
- `POST /api/v1/devices/{id}/commands`：操作用トークン。本文は`command_id`、`operation`、`expires_in_seconds`（画面では15秒）。設備IDの対応はサーバー設定で決まる。
- 指令はDBに保存され、MQTTで設備へ配送される。HTTP 202は登録完了。結果不明の場合は設備状態と結果照会APIで確認する。
- WSSは最大16接続。再接続・サーバー再起動後もDBから状態を再取得する。画面の操作履歴と電力推移はセッション内のみ。
- 過去期間の履歴APIはサーバーに実装済み。監視GUIの期間指定検索画面は未実装。

## 結合テスト

模擬設備と監視クライアントをビルドし、PostgreSQL・Mosquitto・OpenSSL・Pythonテスト依存関係を用意する。

```bash
# 一時Broker・DBスキーマ・証明書でQt同士の開閉指令とWSS通知を検証する
TMRP_TEST_DSN="host=/var/run/postgresql dbname=tmrp_dev user=$(id -un)" \
  .venv/bin/python -m pytest -q tests/integration/collection/test_power_server_integration.py -k operates_real_qt
```

Qt通信試験は画面と同じWSS受信・指令作成処理を使う。GUIの手動クリックやWindowsからVMまでのネットワーク確認は別途必要。
