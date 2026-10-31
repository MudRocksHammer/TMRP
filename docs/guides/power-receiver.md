# 電力遥測の受信サーバー

2026-10-27。TMRP内に実装したMQTT→検証→PostgreSQLの常駐サーバー。
監視クライアント向けの履歴取得・模擬設備への操作指令は[HTTPS API](https-api.md)で提供する。
リアルタイムのデスクトップ配信・最新状態管理はまだ含まない。

まとめて起動するスクリプトと継続送信器は[起動・シミュレーター手順](power-simulator.md)を参照する。

## 受信契約

- MQTT 3.1.1、購読は`tmrp/devices/+/telemetry`、受信QoS 1。
- 本文は[電力契約](../reference/power-telemetry-contract.md)の1.0。台帳登録済みのpower_meterだけ受理し、Topicと本文のdevice_idを照合する。
- サーバーではdevice_id・boot_idを128文字以内、sequence_noを0〜9223372036854775807とする。DBの一意インデックス・BIGINTに対応する追加制約。既存の単件モデル自体の許容範囲は変えていない。
- 本文の既定上限は16384 bytes。UTF-8、JSON構文、重複キー、NaN/Infinity、単独サロゲート、NUL、32段を超えるネストを拒否する。
- retainedフラグ付き配送を拒否する。MQTT 3.1.1ではライブ配送時のretain指定を判別できないため、送信器もretainなしで設定する。
- 旧ロボットTelemetryは受理しない。台帳は起動時に読み込み、変更時はサーバーを再起動する。

## 保存とACK

```text
受信 → 検証 → power_telemetryまたは拒否記録へCOMMIT → MQTT ACK
```

power_telemetryには、識別子・観測時刻・受信時刻・Topic・全フィールドのJSONBを保存する。
一意キーは(device_id, boot_id, sequence_no)。同じキーで正規化後の内容が同じなら重複、異なるならidentity_conflictを拒否記録に残す。元の行と最初の受信時刻を上書きしない。

power_telemetry_rejectionsには理由、受信時刻、Topic（最大512文字）、本文SHA-256とサイズを保存する。本文全体は保存しない。衝突のSHA-256は正規化後の候補本文に対する値。

不正入力も拒否記録のCOMMIT後にACKする。これにより同じ不正入力が無限に再配送されるのを避ける。拒否記録の保存に失敗した場合もACKせず停止する。
received_atはUTCで取得し、機器のevent_timeを置換しない。

初版は同一スレッドで1件ずつ保存する。アプリ内の無制限Queueは持たないが、高負荷性能は未保証。DB statement_timeout=5秒、lock_timeout=3秒、synchronous_commit=onを使用する。DB停止時は受信サーバーも失敗終了し、systemdで再起動する。

Pahoの[手動ACK](https://eclipse.dev/paho/files/paho.mqtt.python/html/client.html)とPsycopgの[transaction](https://www.psycopg.org/psycopg3/docs/basic/transactions.html)を利用する。Brokerの保持設定とDBのfsync・ストレージも永続性に影響する。

## ローカル起動

TMRPルートで実行する。既存ロボット用テーブルは変更しない。

```bash
# SQL資源と新しいCLI登録を含めてパッケージを更新する
.venv/bin/python -m pip install --no-deps --no-build-isolation -e .
# ネットワーク接続なしで設定と台帳を検査する
.venv/bin/python -m myproj.app.receiver --config examples/power/receiver-local.toml --check-config
# ローカルDB接続先を指定する（実運用では専用ロールを使う）
export TMRP_RECEIVER_DSN='host=/var/run/postgresql dbname=tmrp_dev user=shou'
# 電力用の2テーブル・索引を追加する。初回配備時に実行する
.venv/bin/python -m myproj.app.receiver --config examples/power/receiver-local.toml --init-db
# 受信サーバーを起動する。Brokerは127.0.0.1:18884で用意する
.venv/bin/python -m myproj.app.receiver --config examples/power/receiver-local.toml
```

ローカルで匿名Brokerを一時起動する場合の例。既存18883と分ける。

```bash
# この端末で一時Brokerを起動する。永続保存・認証のない開発用
mosquitto -p 18884
```

別端末から確認する。

```bash
# DB接続と購読が成立していればHTTP 200。未準備時は503
curl --fail http://127.0.0.1:8081/health/ready
# 正常データをQoS 1で送信する。同じ入力の再送は二重保存しない
mosquitto_pub -h 127.0.0.1 -p 18884 \
  -t 'tmrp/devices/power-meter-001/telemetry' -q 1 \
  -f examples/power/valid.json
# 保存結果を確認する。Brokerへのpublish成功だけではDB保存完了にならない
psql "$TMRP_RECEIVER_DSN" -c 'SELECT device_id, boot_id, sequence_no, event_time, received_at FROM power_telemetry;'
```

Ctrl+C/SIGTERMでは処理中のトランザクションを終えて停止する。通常終了0、運用障害1、設定・Broker認証／購読拒否2。機密情報をログへ出さないため、DB接続エラーの詳細はPostgreSQL側ログでも確認する。

## Linuxサーバーへの配備

前提: Python 3.12以上、PostgreSQL、MQTT Broker、systemd。資材は`deploy/receiver/`に置く。
以下は配備先で管理者が実行する手順。この変更ではホストのサービス登録や本番への接続は行っていない。

1. TMRPを`/opt/tmrp`へ配置し、専用仮想環境を作る。
2. 専用OSユーザーと設定ディレクトリを作る。
3. 専用DB・ロールを用意し、管理用接続で`--init-db`を実行する。
4. 実行用DBロールには対象スキーマのUSAGE、power_telemetryのSELECT/INSERT、power_telemetry_rejectionsのSELECT/INSERT、関連シーケンスのUSAGEを付与する。HTTPS APIを有効にする場合はdevice_commandsのSELECT/INSERT/UPDATEも必要。DDL権限は不要。
5. Brokerに受信用アカウントを作り、対象Topicの購読だけ許可する。送信機器にも固有の資格情報と、自身のTopicへのpublish権限を与える。
6. 設定、台帳、秘密情報、必要な証明書を配置し、設定検査後にsystemdを起動する。

```bash
# 配備先で専用Python環境を作り、サーバー依存関係を導入する
python3 -m venv /opt/tmrp/.venv
/opt/tmrp/.venv/bin/python -m pip install /opt/tmrp
# OSユーザーを作る（既存の場合は作成しない）
sudo useradd --system --no-create-home --shell /usr/sbin/nologin tmrp
# 設定ディレクトリと台帳・設定例を配置する
sudo install -d -m 0750 -o root -g tmrp /etc/tmrp
sudo install -m 0640 -o root -g tmrp /opt/tmrp/deploy/receiver/receiver.toml /etc/tmrp/receiver.toml
sudo install -m 0640 -o root -g tmrp /opt/tmrp/examples/power/assets.json /etc/tmrp/assets.json
# 秘密情報の例をrootだけ読めるファイルとして配置する
sudo install -m 0600 /opt/tmrp/deploy/receiver/receiver.env.example /etc/tmrp/receiver.env
# 接続先・台帳・秘密情報を実環境の値へ編集する
sudoedit /etc/tmrp/receiver.toml /etc/tmrp/assets.json /etc/tmrp/receiver.env
# 設定と台帳の検査を実行する
sudo -u tmrp /opt/tmrp/.venv/bin/python -m myproj.app.receiver --config /etc/tmrp/receiver.toml --check-config
# unitを配置し、systemdへ読み込ませて起動する
sudo install -m 0644 /opt/tmrp/deploy/receiver/tmrp-receiver.service /etc/systemd/system/tmrp-receiver.service
sudo systemctl daemon-reload
sudo systemctl enable --now tmrp-receiver
# 稼働と受信可能状態を確認する
sudo systemctl status tmrp-receiver
curl --fail http://127.0.0.1:8081/health/ready
sudo journalctl -u tmrp-receiver -n 50 --no-pager
```

例のパスワードは必ず置換する。`/opt/tmrp`はtmrpユーザーが読み取り・実行できる権限にする。証明書・秘密鍵も必要最小限の読み取り権限で配置する。
DB初期化には管理用のTMRP_RECEIVER_DSNを渡して同じ`--init-db`を実行する。実行用アカウントへ恒久的にDDL権限を付けない。`--init-db`は初版スキーマの冪等な作成であり、将来のALTER移行は別途追加する。

遠隔MQTT接続にはtls=trueが必須。ca_file省略時はOSの信頼ストアを利用し、ホスト名を検証する。必要ならcert_file・key_fileをペアで指定する。
遠隔PostgreSQLはDSNでsslmode=verify-fullと信頼するCAを指定する。
パスワードはTMRP_RECEIVER_DSN・TMRP_MQTT_PASSWORD環境変数へ置く。ヘルスHTTPは既定でループバックのみ。外部監視へ公開する場合はネットワーク制限を行う。

## 監視・再接続・復旧

- 各受信でINFOの`telemetry_received`、正常処理後にINFOの`telemetry_processed`を出力する。不正・衝突の処理結果はWARNINGの`telemetry_rejected`、処理失敗はERRORの`telemetry_processing_failed`。
- ログはstderrへJSONで出る。`record.extra`にreceipt_id、Topic、本文バイト数、受信時刻、検証後のdevice_id・boot_id・sequence_no・event_time、outcome、elapsed_msを含む。受信ログと結果ログはreceipt_idで対応付けられる。
- outcomeはstored／duplicate／conflict／rejected。結果ログはDB処理をコミットし、必要なACK要求が成功した後に出す。ack_requestedはクライアントAPIへのACK要求であり、BrokerがそのACKを受信した証明ではない。
- 失敗ログのstageはvalidation／persist_telemetry／persist_rejection／acknowledge。persistence_completed=trueならDB処理は完了している。例外本文・本文全体は出力せず、例外型と拒否理由コードを記録する。
- 1件ごとのログなので送信量に応じてログ量も増える。systemd運用ではjournaldの保持容量を設定する。
- `/health/live`: 主処理の進行を監視。15秒以上進まなければ503。
- `/health/ready`: 主処理が進行し、DB確認・MQTT購読が成立していれば200。DBは無通信時にも約5秒間隔で確認する。
- 応答にstored/duplicate/conflict/rejectedのプロセス内カウンターを含む。再起動でリセットされ、DB総件数ではない。
- Broker切断は1〜30秒の指数バックオフで再接続する。待機中はlive=200、ready=503。
- DB保存／ACK失敗は終了コード1。systemdが5秒後に再起動する。設定拒否の2は自動再起動しない。
- 同じclient_idを再起動後も維持し、同時に複数プロセスで使わない。
- Brokerで永続セッション、保存、キュー上限、パケット上限を設定する。受信本文上限の検査時にはPahoが既に読み込んでいるのでBrokerのサイズ制限も必要。
- Brokerの保持容量を超えた場合、初回購読前、QoS 0、Broker／DBのディスク喪失などの欠損までは保証しない。
- バックアップ、保持期間、DB容量とBroker滞留の監視は運用前に設定する。自動削除・HA・負荷保証は今回の実装には含まない。

## 検証

```bash
# 既存機能を含め、静的検査と実DBテストを実行する
bash scripts/dev/check_test.sh --db
# 新受信サーバーのDB・MQTT結合テストだけを実行する
TMRP_TEST_DSN='host=/var/run/postgresql dbname=tmrp_dev user=shou' \
  .venv/bin/python -m pytest -q tests/integration/collection/test_power_server_integration.py
```

結合テストはランダム名の専用スキーマと一時Brokerを作成し、終了時に片付ける。既存テーブルへ書き込まない。テストDBロールにはスキーマ作成権限が必要。
TMRP_TEST_DSN未設定時はDBテスト、Mosquittoがない場合は実通信テストがskipされる。リリース確認ではskipなしの実行を必要とする。
