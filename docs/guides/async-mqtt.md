# 非同期MQTT購読とDB保存

`subscribe_telemetry_async.py`は、aiomqttで受信したデータを検証し、
容量2のQueueを通してPostgreSQLへ非同期保存する。受信10件で入力を終了し、
端数保存とconsumerの終了を待って実挿入件数を表示する。

## 準備

[MQTTの準備](mqtt.md#準備)と[DB・テーブルの準備](storage.md)を完了し、
TMRPのルートから実行する。本体の依存関係にaiomqttとpsycopgを含む。

```bash
# プロジェクトと開発用依存関係を仮想環境へインストールする
.venv/bin/python -m pip install -e ".[dev]"
```

接続先はスクリプト内で固定している。

| 項目 | 値 |
|---|---|
| MQTT | 127.0.0.1:18883 |
| 購読 | tmrp/devices/+/telemetry、QoS 1 |
| PostgreSQL | host=/var/run/postgresql port=5432 dbname=tmrp_dev user=shou |
| DB接続 | autocommit=True、timezone=UTC |
| 受信上限 | 10件 |
| 保存条件 | 3件、最初の保存待ちから1秒、または正常終了通知 |

手動実行は通常の`telemetry_messages`テーブルへ保存する。
他のsubscriberは停止し、この受信側だけを起動する。他のpublisherからも送らない状態で確認する。

## 3つのターミナルで実行する

ターミナルAでBrokerを起動する。既に18883で起動中なら、そのBrokerを使用する。

```bash
# MQTT Brokerを起動し、接続と通信のログを表示する
mosquitto -p 18883 -v
```

ターミナルBで受信側を起動する。

```bash
# MQTTの受信10件を検証・保存し、正常終了する
.venv/bin/python scripts/mqtt/subscribe_telemetry_async.py
```

`Subscribed to topic: tmrp/devices/+/telemetry`が表示されてから送信する。
この表示は`await client.subscribe(...)`が完了した後に出る。

ターミナルCで件数を記録し、既存のpublisherを実行する。

```bash
# 送信前のDB件数をNとして記録する。-Xは個人設定を無視し、-cはSQLを実行する。
psql -X -h /var/run/postgresql -p 5432 -U shou -d tmrp_dev \
  -c 'SELECT COUNT(*) FROM telemetry_messages;'

# robot-001とrobot-002から各5件、合計10件を送信する
.venv/bin/python scripts/mqtt/publish_telemetry.py
```

他の通信・再配信がない正常な実行では、ターミナルBに次の結果が出て自動終了する。

```text
Inserted 10 messages into the database
```

終了後にターミナルCで確認する。

```bash
# 他の書き込みがない場合、送信前のNから10件増えたことを確認する
psql -X -h /var/run/postgresql -p 5432 -U shou -d tmrp_dev \
  -c 'SELECT COUNT(*) FROM telemetry_messages;'
```

送信側の終了だけでは保存成功は分からない。受信側の挿入件数とDBの増分を確認する。
時間保存も行うため、バッチの分割が必ず3・3・3・1になるわけではない。
publisherを再実行するとevent_timeが変わり、新しいイベントとして保存される。

## 件数と終了の意味

| 件数 | 意味 |
|---|---|
| take_messagesの上限 | 検証前に受信したMQTTメッセージ数 |
| produce_mqttの戻り値 | 検証を通過してQueueへ投入した件数 |
| run_mqtt_db_pipelineの戻り値 | 重複を除いてDBへ実際に挿入した件数 |

不正入力とQoS 1の再配信も受信上限に数えるため、受信10件でも新規保存が10件未満になる場合がある。
不正入力はLoguruのWARNINGで理由を表示して除外し、次の入力へ進む。
このスクリプトはCLIのJSONログ設定を読み込まない。購読開始と最終件数はprintで表示する。

`take_messages`は10件目をyieldし、その処理が戻った直後に終了する。
次のループの先頭で件数を判定すると、11件目を待ってしまう。
入力が10件に達しない間は受信待ちを続ける。受信全体のタイムアウトは設定していない。
保存待ちの正常データは、上限に達する前でも保存期限により保存される。

正常終了では管理関数がNoneを送り、consumerが端数を保存して戻る。
Ctrl+Cはキャンセルとして扱い、接続を閉じるが、未保存データの保存は保証しない。
DB例外でも受信側をキャンセルして終了する。保存済みの先行バッチまで取り消す処理ではない。
再接続、自動再試行、未保存データの永続保持は未実装。
実装上の詳細は[非同期パイプライン](async-pipeline.md#mqtt購読との接続)を参照する。

## 同期版との違い

| 項目 | subscribe_telemetry.py | subscribe_telemetry_async.py |
|---|---|---|
| MQTT処理 | Pahoのコールバック | aiomqttの非同期反復 |
| 保存 | 3件またはCtrl+C | 3件・保存期限・正常終了通知 |
| 正常な終了条件 | Ctrl+C | 受信10件 |
| Ctrl+C時の残件 | 保存を試みる | 保存保証なし |

同期版の不正入力手順は継続購読が前提なので、非同期版の10件上限と混同しない。
MQTT受信確認とDBの保存完了は別で、プロセス停止を越えた配送保証はない。

## 自動テストと検証範囲

```bash
# Broker・DB不要で、MQTT処理と件数制限の21ケースを確認する
.venv/bin/python -m pytest tests/units/collection/test_async_mqtt.py -q

# 実DBの一時テーブルで、不正入力の除外・5件保存・再投入時0件と全行不変を確認する
TMRP_TEST_DSN='host=/var/run/postgresql port=5432 dbname=tmrp_dev user=shou' \
  .venv/bin/python -m pytest tests/integration/collection/test_async_mqtt_integration.py -q

# 自動整形・静的解析・型検査・実DBを含む全テストを実行する
bash scripts/dev/check_test.sh --db
```

単体テストは保存モックと有限入力を使う。終了時のテストはEventで開始を同期し、
asyncio.runの終了処理より前に両タスクの終了を確認する。
件数制限の回帰テストは、上限の次の入力を取得したらAssertionErrorになる入力を使う。

結合テストは本物の検証・Queue・DB保存を実行するが、MQTT入力はテスト内で用意する。
自動テストではBrokerへ接続しない。実通信は上記の手順で別途確認する。
2026-10-22には、専用の一時Brokerと実DBの一時テーブルで10件の受信・保存内容・自動終了を確認した。
この確認では通常の保存テーブルは変更していない。

2026-10-22の全体検証は、DBあり350件成功、DB設定なし327件成功・23件skip。
Ruff・50ファイルの書式・本体20ファイルのmypyも成功した。
