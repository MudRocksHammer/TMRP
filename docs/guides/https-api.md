# 監視クライアント用HTTPS API

監視クライアントはHTTPSで履歴を取得し、模擬設備へ開閉指令を送る。
遥測と設備への指令配送には引き続きMQTTを使う。

```text
監視クライアント ─ HTTPS :8443 → Pythonサーバー ─ PostgreSQL
                                      │
                                      └ MQTT → 模擬設備 → 操作結果
```

## 起動

UbuntuのTMRPルートで実行する。PostgreSQLとMosquitto（127.0.0.1:18884）は起動しておく。
既存の受信サーバーを停止してからHTTPS対応の設定で起動する。

```bash
# APIの依存関係を導入する
.venv/bin/python -m pip install -e '.[dev]'

# 既存のサーバー証明書と秘密鍵を配置する（Gitには含めない）
install -d -m 700 .local/https
install -m 600 ~/tmrp-mqtt-tls/server.crt .local/https/server.crt
install -m 600 ~/tmrp-mqtt-tls/server.key .local/https/server.key

# 初回のみ、読み取り用と操作用の異なるトークンを生成する
# ファイルが既存の場合は上書きせず停止する
.venv/bin/python - <<'PY'
import os
import secrets
os.umask(0o077)
with open('.local/https/api.env', 'x') as target:
    for name in ('TMRP_API_READ_TOKEN', 'TMRP_API_CONTROL_TOKEN'):
        target.write(f'{name}={secrets.token_hex(32)}\n')
PY

# トークンをこの端末の環境変数へ読み込む
set -a
source .local/https/api.env
set +a

# DB接続先を指定し、テーブル・索引の追加後にサーバーを起動する
export TMRP_RECEIVER_DSN="host=/var/run/postgresql dbname=tmrp_dev user=$(id -un)"
bash scripts/server/start_server.sh --config examples/power/receiver-https.toml --init-db
```

証明書はSANに接続先IP（例：`192.168.237.128`）を含むものを使う。
HTTPSの証明書設定はMQTTの`tls`・`cert_file`・`key_file`とは別。

| 設定 | 意味 |
|---|---|
| `api_enabled` | HTTPS APIを有効にする。既定はfalse |
| `api_host` / `api_port` | API待受アドレス・ポート。例は0.0.0.0:8443 |
| `api_cert_file` / `api_key_file` | PEM形式のサーバー証明書と対応する秘密鍵。相対パスはTOMLの位置が基準 |
| `[api_command_targets]` | 操作を許可する機器IDと設備ID。設備台帳への登録も必要 |

起動前に証明書とトークンを検査する。不備があれば終了コード2で停止する。
API無効時は従来のMQTT受信とローカルHTTPヘルスチェックだけを起動する。
TLSは1.2以上。平文HTTPへの自動切替は行わない。

## Windowsから確認

CA証明書を`C:\Users\xiaor\tmrp-certs\ca.crt`へコピーしておく。
`.local/https/api.env`の読み取り用トークンを、次の入力欄へ貼り付ける。
HTTPの`Authorization`ヘッダーで渡す。MQTT用のユーザー名・パスワードとは別。

```powershell
# API接続先・CA・読み取り用トークンを設定する
$base = 'https://192.168.237.128:8443'
$ca = "$env:USERPROFILE\tmrp-certs\ca.crt"
$readToken = Read-Host 'TMRP_API_READ_TOKEN'

# 設備一覧を取得する（PowerShellの別名を避けてcurl.exeを指定）
curl.exe --fail-with-body --cacert $ca -H "Authorization: Bearer $readToken" "$base/api/v1/devices"

# 履歴を取得する。期間は実際の保存時刻に合わせる
curl.exe --fail-with-body --cacert $ca -H "Authorization: Bearer $readToken" `
  "$base/api/v1/devices/power-meter-001/telemetry?start=2026-10-31T00:00:00Z&end=2026-11-01T00:00:00Z&limit=100"
```

`start`を含み`end`を含まない期間で取得する。時刻にはUTCの`Z`またはオフセットが必須。
期間は最大31日、`limit`は1〜1000件。応答の`items`に`telemetry`と`received_at`が入り、
続きがあれば`next_cursor`を返す。同じ機器・期間の次の要求に`cursor`としてURLエンコードして渡す。
同じ観測時刻のデータもboot_id・sequence_noを含む順序で取得する。
ページ間に遅れて保存された過去データは、期間を再取得して確認する。

## 指令を送る

操作用トークンは読み取りにも使える。読み取り用トークンでは操作できない。
Qt模擬設備を同じBrokerへ接続し、遠方操作を許可しておく。

```powershell
# 操作用トークンと、今回の操作を識別するIDを用意する
$controlToken = Read-Host 'TMRP_API_CONTROL_TOKEN'
$commandId = [guid]::NewGuid().ToString()

# 指令JSONをUTF-8ファイルへ保存する
$body = @{ command_id = $commandId; operation = 'open_breaker'; expires_in_seconds = 60 } | ConvertTo-Json
$commandFile = Join-Path $env:TEMP "tmrp-command-$commandId.json"
[IO.File]::WriteAllText($commandFile, $body, [Text.UTF8Encoding]::new($false))

# 指令を登録する。HTTP 202はDBへの登録完了を示す
curl.exe --fail-with-body --cacert $ca -H "Authorization: Bearer $controlToken" `
  -H 'Content-Type: application/json' --data-binary "@$commandFile" `
  "$base/api/v1/devices/power-meter-001/commands"

# 設備からの結果を照会する
curl.exe --fail-with-body --cacert $ca -H "Authorization: Bearer $readToken" `
  "$base/api/v1/devices/power-meter-001/commands/$commandId"
```

`operation`は`open_breaker`または`close_breaker`。有効期間は1〜300秒。
必要なら`expected_state_version`を指定し、模擬設備側で操作前の状態版を照合する。
通信が途切れた場合は同じJSONファイルを再送する。同じ機器・指令ID・内容なら既存指令を返し、
同じIDで内容を変えると409になる。再試行のために新しいIDを生成しない。

| `status` | 意味 |
|---|---|
| `queued` | DBに保存済み、配送処理待ち |
| `awaiting_result` | 配送を試行済み、設備の応答待ち |
| `accepted` | 設備が受け付け、実行中 |
| `completed` | 設備から完了応答を受信 |
| `rejected` / `failed` | 設備から拒否／失敗応答を受信 |
| `unknown` | 最終結果を受信せず期限切れ。操作されたかは未確定 |

指令の本文はDBへ保存し、最終結果が届くか期限が切れるまで5秒間隔で再送する。
再起動後も同じID・本文を使う。期限切れ後に届いた最終結果も保存する。
`publish_attempts`は配送試行回数であり、Broker到達・操作完了の証明ではない。
操作の二重実行防止は模擬設備側の指令ID履歴と組み合わせる。

## API一覧

| メソッド・パス | 用途 |
|---|---|
| `GET /health/ready` | 受信サーバーの稼働状態 |
| `GET /api/v1/devices` | 登録機器と操作対象設備 |
| `GET /api/v1/devices/{id}/telemetry` | 期間指定の履歴取得 |
| `POST /api/v1/devices/{id}/commands` | 操作指令の登録 |
| `GET /api/v1/devices/{id}/commands/{command_id}` | 操作結果の照会 |

全APIでBearer認証が必要。JSON不正400、未認証401、権限不足403、対象なし404、ID競合409、
本文上限超過413、入力不正422、DB停止・接続数上限503を返す。
本文上限16KiB、履歴SQLの待ち時間5秒、API同時接続の上限32。

systemdで起動する場合は`/etc/tmrp/receiver.env`へトークンを設定し、
証明書と秘密鍵を`tmrp`ユーザーが読める`/etc/tmrp/tls/`へ配置する。
`ProtectHome=true`のためホームディレクトリの証明書は使わない。
実行用DBロールには`power_telemetry`のSELECTと、`device_commands`のSELECT／INSERT／UPDATEが必要。
MQTT受信アカウントには遥測購読に加え、操作対象の`commands`へのpublishと`command-results`のQoS 1購読を許可する。
設備側のMQTTアカウントも自身の指令・結果Topicだけに制限する。

現在の認証は読み取り／操作の共有トークン。利用者別アカウント・設備別権限・ブラウザー向けCORSは未実装。
このAPIの操作対象は模擬設備。既存のQt模擬設備アプリはMQTT接続のままで、監視画面は別途APIを呼び出す。
