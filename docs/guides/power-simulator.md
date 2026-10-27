# 起動スクリプトと電力データの継続送信

既存のscripts/mqtt/publish_telemetry.pyは、ロボット2台を5回送って終了するスクリプト。
電力データの継続送信にはscripts/mqtt/simulate_power.pyを使用する。

## 既定の送信条件

- 台帳examples/power/assets.jsonの12機器。
- 各機器1 Hz、合計12メッセージ/秒を目標とする。
- 送信は約1/12秒ごとに機器を切り替え、1秒間に12機器を一巡する。
- QoS 1、retainなし。Ctrl+C/SIGTERMまで継続する。
- 起動ごとに新しいboot_idを発行し、機器ごとのsequence_noは0から増加する。
- 電圧・周波数は試験値、電流・電力は緩やかな周期変化とseed付き乱数で変化する。
- 現在はclosed・goodの通常運転データ。遮断器操作や欠損シナリオは生成しない。

12機器×1 Hzは電力監視の開始条件。設備数・頻度は実調査による確定値ではない。
全鉱区334件/秒や以前の70000件/秒を既定設定にはしていない。

## 3つの端末で起動する

すべてTMRPルートから実行する。PostgreSQLは起動済みとする。

端末1: Brokerが動いていない場合だけ起動する。

```bash
# 開発用Brokerを18884番で起動する。永続化・認証のないローカル検証用
mosquitto -p 18884
```

端末2: 受信サーバーを起動する。

```bash
# PostgreSQL接続先を設定する。userは自分の環境のDBロールへ変更する
export TMRP_RECEIVER_DSN='host=/var/run/postgresql dbname=tmrp_dev user=shou'
# 設定検査・電力テーブルの初期化後、サーバーを前景起動する
bash scripts/server/start_server.sh --init-db
```

テーブルが作成済みなら--init-dbを省略できる。初期化は既存データを削除しない。
--configで別設定、TMRP_PYTHONでPython実行ファイルを指定できる。
スクリプトは資格情報を表示せず、最終的にexecでPythonへ置き換わるため、SIGTERMがサーバーへ直接届く。
Broker・PostgreSQL自体の起動やsystemd登録は行わない。systemdを使う配備は[受信サーバー手順](power-receiver.md)を参照。

端末3: 受信可能状態を確認して送信する。

```bash
# HTTP 200ならDB確認とMQTT購読が成立している
curl --fail http://127.0.0.1:8081/health/ready
# 12機器×1 Hzで、Ctrl+Cまで電力データを送信する
.venv/bin/python scripts/mqtt/simulate_power.py
```

停止は各端末のCtrl+C。送信器を先に止め、サーバー、Brokerの順に止めると確認しやすい。

## 頻度と実行回数

```bash
# 各機器を10 Hzに変更する。12機器なら合計120メッセージ/秒が目標
.venv/bin/python scripts/mqtt/simulate_power.py --rate-hz 10
# 全体334件/秒に相当する負荷を、12機器の電力メッセージで模擬する
.venv/bin/python scripts/mqtt/simulate_power.py --total-rate 334
# 各機器5件、合計60件の送信確認後に終了する
.venv/bin/python scripts/mqtt/simulate_power.py --cycles 5
# 送信器専用の接続・台帳設定と乱数seedを指定する
.venv/bin/python scripts/mqtt/simulate_power.py --config examples/power/simulator-local.toml --seed 123
```

--rate-hzは機器ごとの頻度、--total-rateは全体の件数で、同時指定はできない。
--total-rate 334は全鉱区の各設備種・項目を再現するものではない。電力メッセージだけの相当件数の試験。
--cyclesの既定0は無期限。1回の巡回で台帳の各機器に1件ずつ送信する。

実際の送信速度はネットワークとBrokerに依存する。10秒ごとのログにtargetと比較できる実測平均件数を表示する。
通信が遅れた場合、過去の観測を大量生成して追い付き送信することはしない。

## 接続と再送

- 既定接続は127.0.0.1:18884。接続先・TLS・台帳はsimulator-local.tomlから読む。
- 接続設定の書式は受信サーバーと共通。送信器ではhealth設定は使わず、MQTT client_idは起動ごとにsim-UUIDを生成するため、受信サーバーの接続を奪わない。
- 実環境では送信専用アカウントを設定する。パスワードはTMRP_SIMULATOR_PASSWORDから取得し、受信アカウントとは分ける。
- 遠隔BrokerではTLSが必要。認証拒否やTLS設定不備は終了コード2になる。
- Broker確認待ちは一度に1件。切断・確認タイムアウト時は同じboot_id・sequence_no・時刻・内容で再接続後に再送する。
- 再送が重複して到着する場合は受信サーバーが一意キーで処理する。
- このシミュレーターの未確認メッセージはメモリ上にある。プロセス強制終了や再起動をまたぐ送信保証はない。
- 通信停止中は新しい観測を生成しない。再開後は現在時刻の観測を生成する。

ログのbroker_confirmedはBrokerが受領を確認した件数であり、サーバーのDB保存件数ではない。
DB保存件数や重複・拒否は受信サーバーとDBで別途確認する。

## 検証

生成値・連番・seed再現性・送信周期の計算・再接続時の同一イベント再送を単体テストする。
結合テストでは起動スクリプトからサーバーを立ち上げ、12機器×2回の24件保存と、無期限送信のSIGTERM終了を確認する。
