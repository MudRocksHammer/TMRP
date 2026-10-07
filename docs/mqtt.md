# MQTT送受信の再現手順

ローカルのMosquitto Brokerを介し、Pythonシミュレーターから2台分のTelemetryを送信する。
Python受信側はトピックとJSON本文を検証し、正常データを表示する。不正データは理由を表示して拒否し、次の受信を続ける。

```text
publish_telemetry.py → Mosquitto → subscribe_telemetry.py
                                  └ parse_mqtt_telemetry → TelemetryMessage
```

現在は学習用の送受信スクリプト。DB・ファイルへの受信データ保存や重複排除はまだ実装していない。

## 準備

Python 3.12以降、Ubuntu／WSL上のMosquitto 2系以降を使用する。
Pythonとプロジェクトの初期セットアップは[README](../README.md#setup)を参照する。
以下のPythonコマンドとファイルを使う送信コマンドは、TMRPのルートで実行する。

```bash
# インストール可能なUbuntuパッケージの情報を更新する
sudo apt update

# Brokerと送受信用コマンドをインストールする
sudo apt install mosquitto mosquitto-clients

# 本体・MQTTライブラリ・開発ツールを既存の仮想環境へインストールする
.venv/bin/python -m pip install -e ".[dev]"
```

`paho-mqtt`は本体の依存関係に含まれる。MQTTの課題だけならanalysis追加依存関係は不要。
接続先は送受信スクリプト内で`127.0.0.1:18883`に固定している。
標準ポート1883とは別の学習用ポートを使う。

## 1. Brokerを起動する（ターミナルA）

```bash
# ポート18883でBrokerを起動し、接続・購読・送信のログを表示する
mosquitto -p 18883 -v
```

この端末は起動したままにする。設定ファイルを渡さずこの方法で起動したMosquitto 2系以降は、ループバックで待ち受ける。
[Brokerの公式説明](https://mosquitto.org/man/mosquitto-8.html)

## 2. Python受信側を起動する（ターミナルB）

TMRPのルートから実行する。

```bash
# 全デバイスのTelemetryを購読し、検証結果を表示する
.venv/bin/python scripts/subscribe_telemetry.py
```

`brokerに接続しました`と表示される。
この表示は購読要求を出した時点のもので、購読完了の確認ではない。
ターミナルAで該当クライアントへの`Sending SUBACK`を確認してから送信する。
受信側は起動したままにする。

## 3. 2台分を送信する（ターミナルC）

TMRPのルートから実行する。

```bash
# robot-001とrobot-002のTelemetryを各5件送信する
.venv/bin/python scripts/publish_telemetry.py
```

送信側には次のように5行表示され、終了する。

```text
連番1: 2件をBrokerへ送信しました
連番2: 2件をBrokerへ送信しました
連番3: 2件をBrokerへ送信しました
連番4: 2件をBrokerへ送信しました
連番5: 2件をBrokerへ送信しました
```

| 項目 | 内容 |
|---|---|
| デバイス | robot-001、robot-002 |
| 連番 | 各デバイスで1〜5（実行ごとに1から開始） |
| robot-001の残量 | 100、98、96、92、90 |
| robot-002の残量 | 80、78、76、74、70 |
| event_time | 各メッセージ生成時のUTC現在時刻 |
| 間隔 | 2台分の送信完了後に1秒待つ。最終回は待たない |
| 配信設定 | QoS 1、retain=False |

通常のローカル接続では、受信側に`解析成功:`が合計10件表示される。
各デバイスの連番1〜5と、`解析失敗:`が出ていないことを確認する。
時刻は実行ごとに変わり、送信処理にかかる時間もあるため厳密な1秒周期ではない。

`publish.multiple()`は毎回接続し、2件を送信して切断する。送信側の完了は受信側の検証成功を保証しないので、両方の表示を確認する。
[送信ヘルパーの公式説明](https://eclipse.dev/paho/files/paho.mqtt.python/html/helpers.html)

## トピックと本文の規約

送信トピックは`tmrp/devices/{device_id}/telemetry`、購読フィルターは`tmrp/devices/+/telemetry`。
`+`は1階層に一致する。`tmrp`のスペルと大文字・小文字も一致させる。

`parse_mqtt_telemetry(topic: str, payload: bytes)`は次の順に検証する。

1. `/`で分けて4階層であること。
2. 第1階層が`tmrp`、第2階層が`devices`、第3階層が空でなく、第4階層が`telemetry`であること。
3. 本文がUTF-8としてデコードでき、[Telemetry契約](telemetry-contract.md)に従うJSONであること。
4. トピックのデバイスIDと本文の`device_id`が一致すること。

成功時は`TelemetryMessage`を返す。不正UTF-8は`UnicodeDecodeError`、トピック・JSON・モデルの検証失敗は`TelemetryValidationError`になる。
受信コールバックが両方を捕捉し、標準エラーに`解析失敗:`を表示する。成功は標準出力に表示する。
現在の送受信スクリプトはprintを使用し、CLIのJSONログ設定は適用しない。

## 4. 不正入力の後も受信できるか確認する

BrokerとPython受信側を起動したまま、ターミナルCから順に送信する。

```bash
# JSONとして解析できない本文を送信する
mosquitto_pub -h 127.0.0.1 -p 18883 \
  -t 'tmrp/devices/robot-001/telemetry' -q 1 -m 'not-json'

# JSONとしては正しいが、必須項目がない本文を送信する
mosquitto_pub -h 127.0.0.1 -p 18883 \
  -t 'tmrp/devices/robot-001/telemetry' -q 1 -m '{}'

# 不正なUTF-8バイトを生成し、標準入力を本文として送信する（-s）
.venv/bin/python -c 'import sys; sys.stdout.buffer.write(bytes([255]))' |
  mosquitto_pub -h 127.0.0.1 -p 18883 \
    -t 'tmrp/devices/robot-001/telemetry' -q 1 -s

# 本文のrobot-001と異なるデバイスのトピックへ送信する
mosquitto_pub -h 127.0.0.1 -p 18883 \
  -t 'tmrp/devices/robot-002/telemetry' \
  -q 1 -f examples/telemetry/valid.json

# 正常なトピックへ送信し、拒否後も受信できることを確認する
mosquitto_pub -h 127.0.0.1 -p 18883 \
  -t 'tmrp/devices/robot-001/telemetry' \
  -q 1 -f examples/telemetry/valid.json
```

期待結果は、4件の`解析失敗:`の後に1件の`解析成功:`が表示され、受信側が終了しないこと。
最後のサンプルは`device_id=robot-001`、`sequence_no=1001`。
このvalid.jsonは固定サンプルなので、event_timeも固定値であり現在時刻ではない。

購読フィルターに一致しないトピックはコールバックへ届かない。
階層不足や接頭辞違いなどは、次の単体テストで検証関数を直接呼んで確認する。

## 品質チェック

```bash
# Brokerを起動せず、MQTT検証関数の正常・異常ケースをテストする
.venv/bin/python -m pytest tests/units/test_mqtt_validation.py -v

# 本体・テスト・スクリプトのコード規約を、自動修正せず確認する
.venv/bin/python -m ruff check src tests scripts

# 同じ対象の書式を、自動修正せず確認する
.venv/bin/python -m ruff format --check src tests scripts

# src内をstrict設定で型検査する
.venv/bin/python -m mypy

# 既存機能を含む全テストを実行する
.venv/bin/python -m pytest -q
```

単体テストはBrokerとの実通信を検証しない。送受信の確認には上記の3端末による手順も実行する。
`scripts/check_test.sh`のRuff対象はsrcとtestsのみなので、送受信スクリプトは上記コマンドで検査する。

## 終了方法と現在の制約

送信側は5回の送信後に終了する。受信側はターミナルBでCtrl+Cを押すと`終了します`を表示し、切断する。
最後にターミナルAでCtrl+Cを押して、手動起動したBrokerを停止する。
Ubuntuパッケージのインストールで別途起動した標準ポート1883のサービスがある場合、この操作ではそのサービスは停止しない。

- retain=Falseなので、新しく購読を始めたクライアントへ過去の送信内容は再配信されない。受信側を先に起動する。
- QoS 1では再送による重複が起こり得る。現段階の受信側は重複排除を行わない。
- 実行し直すと連番は1へ戻る。将来の永続化では、再起動と重複を区別する設計が必要。
- Broker停止時の再接続・再送や、接続失敗時の運用向けエラー処理は、今回の検証範囲に含めていない。

## 困ったとき

| 症状 | 確認事項 |
|---|---|
| 接続を拒否される | Brokerが起動しているか、送受信側とも127.0.0.1:18883を使っているか |
| Address already in use | 同じポートでBrokerがすでに動いていないか。既存Brokerを使う場合は二重起動しない |
| 送信は終了したが受信表示がない | 受信側の購読完了後に送ったか、トピックがtrmpではなくtmrpか |
| 修正後も以前と同じエラーになる | ファイルを保存し、動作中の受信スクリプトをCtrl+Cで終了して再起動したか |
| 不正UTF-8で受信側が終了する | tryの外でpayload.decode()を呼んでいないか |

```bash
# 学習用ポートで待ち受けているプロセスを確認する
ss -ltnp 'sport = :18883'
```
