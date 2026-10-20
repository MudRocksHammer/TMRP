# asyncioによるTelemetry処理と比較実験

Week 9の基礎演習として、固定JSONLから読み込んだTelemetryに受信待ちを模した遅延を加え、
同期・非同期・Queue経由の3方式で同じアラートが得られることを確認する。
さらに、QueueからPostgreSQLへ非同期で一括保存するパイプラインを実装している。

実装は[src/myproj/processing/async_pipeline.py](../../src/myproj/processing/async_pipeline.py)、
比較スクリプトは[scripts/processing/compare_async_telemetry.py](../../scripts/processing/compare_async_telemetry.py)。
アラートの閾値と状態遷移は[低バッテリーアラート](alerts.md)を参照する。

## Queueによる処理の分離

```text
デバイス別producer ── put ──> Queue(maxsize=2) ── get ──> consumer
    受信待ちを模擬                                      Monitorで判定
```

- `produce()`は、メッセージごとに`asyncio.sleep(delay)`を待ち、Queueへ追加する。
- `consume()`は、1個のMonitorで全デバイスを判定し、発生・復帰イベントをリストに保持する。
- `run_pipeline()`は、producer群とconsumerをTaskGroupで管理し、終了後にイベントを返す。

Queueが満杯なら`put()`は空きができるまで待つ。これをバックプレッシャーと呼ぶ。
同じデバイスの入力は1つのproducerにまとめ、リストの順序を維持する。
異なるデバイスの処理順序は固定しない。入力の自動ソートや重複排除は行わない。

### 正常終了

全producerの終了後、run_pipelineが終了通知の`None`を1回だけ送る。
consumerはそれを受け取るとイベントリストを返す。
各producerから終了通知を送ると、短いデバイスの処理が終わった時点でconsumerが終了し、
残りのproducerが満杯のQueueで待ち続けるおそれがある。

consumerは`get()`で取り出した各項目について、`finally`で`task_done()`を1回呼ぶ。
終了通知も対象に含め、`queue.join()`が全項目の完了通知を待てるようにする。
メッセージ内の`battery_percent=None`は欠損値であり、Queueに入れる終了通知の`None`とは異なる。

### 失敗とキャンセル

consumerが例外で失敗すると、TaskGroupによるキャンセルがproducer群へ伝わり、
後始末を待ってから呼び出し元へ例外を伝える。テストしたRuntimeErrorはExceptionGroupで受け取る。
呼び出し元からrun_pipelineのTaskをキャンセルした場合は、producerとconsumerの終了を待ち、
CancelledErrorを呼び出し元へ伝える。

異常終了時は全メッセージの処理完了を保証しない。task_doneはQueueの管理上の通知であり、
永続化や配送完了を表すものではない。

## 3方式の比較を実行する

READMEの手順で本体と開発用依存関係をインストールし、TMRPのルートで実行する。
標準ライブラリのasyncioを使うため、非同期用の追加パッケージは不要。

```bash
# 同期・gather・Queueを各5回実行し、結果の一致と測定値をCSVへ保存する
.venv/bin/python scripts/processing/compare_async_telemetry.py

# 保存した15回分の測定結果を確認する
cat reports/async_benchmark.csv
```

入力は[固定JSONL](../../examples/telemetry/battery_alerts.jsonl)の8件。
robot-001が6件、robot-002が2件で、各メッセージの待ち時間は0.05秒とする。

| mode | 実行方法 | 待ち時間だけから計算した目安 |
|---|---|---|
| sync | 各デバイスを順に処理 | (6 + 2) × 0.05 = 0.4秒 |
| gather | デバイス別の処理を並行実行 | max(6, 2) × 0.05 = 0.3秒 |
| queue | producer群から1つのconsumerへ渡す | 約0.3秒とQueue処理の負担 |

各回でsync、gather、queueの順に実行する。呼び出しごとにMonitorは初期状態になる。
毎回5イベントが得られることと、device_id・sequence_noで並べた全イベントの一致を確認する。
同期版の戻り値は入れ子のため、計測後に平坦化する。gather版は関数内で平坦化して返す。

### 計測範囲とCSV

時間は`time.perf_counter()`の差で測る。入力読み込み、グループ分け、結果の比較、CSV出力は計測範囲外。
非同期2方式では`asyncio.run()`のイベントループ生成・終了も含む。
gather版は関数内の平坦化も含むため、各方式の実装を呼び出したときの所要時間を比較している。

全検証の成功後、[reports/async_benchmark.csv](../../reports/async_benchmark.csv)を上書きする。
再実行してもヘッダー1行とデータ15行になり、追記はしない。

```csv
mode,run,device_count,message_count,delay_seconds,event_count,elapsed_seconds
```

runは1〜5、device_countは2、message_countは8、delay_secondsは0.05、event_countは5。
elapsed_secondsにはその1回分の実測時間を保存する。画面には各方式の最小値と中央値を表示する。

2026-10-16に取得した保存済みCSVの集計（秒）:

| mode | 最小値 | 中央値 |
|---|---:|---:|
| sync | 0.404 | 0.405 |
| gather | 0.304 | 0.304 |
| queue | 0.304 | 0.305 |

このCSVは実測例として管理する。再実行時の時間は環境や負荷によって変わるため、
同じ秒数を再現することや、必ず特定の方式が最速になることは完了条件にしない。
ここで確認できるのは模擬的な待ち時間の重なりであり、MQTT・DBやCPU負荷の高い処理の性能ではない。

## 自動テスト

[tests/units/processing/test_async_pipeline.py](../../tests/units/processing/test_async_pipeline.py)には7ケースがある。

| 内容 | ケース数 |
|---|---:|
| 固定入力から期待する5イベントを生成 | 1 |
| 空辞書・空のデバイスリストで終了 | 2 |
| 終了通知だけでconsumerとjoinが完了 | 1 |
| 満杯でproducerが待機し、空きができると再開 | 1 |
| consumerの失敗でproducerの後始末も完了 | 1 |
| 外部キャンセルで両タスクの後始末が完了 | 1 |

通常のpytest関数からasyncio.runを呼ぶ。停止の検出には1秒のwait_forを使う。
開始タイミングはEventで同期し、固定sleepの長さで成功を判定しない。
pytest.raises後の内容確認はwithブロックの外、後始末の確認はasyncio.run終了前のscenario内に置く。

```bash
# Queue処理の7ケースを実行する（DB不要）
.venv/bin/python -m pytest -q tests/units/processing/test_async_pipeline.py

# DB設定を除いて、整形・lint・型・既存テスト全体を検査する
# TMRP_TEST_DSNが必要なDBテストはskipする
env -u TMRP_TEST_DSN bash scripts/dev/check_test.sh

# srcに加え、比較スクリプトとQueueテストも型検査する
.venv/bin/python -m mypy src scripts/processing/compare_async_telemetry.py tests/units/processing/test_async_pipeline.py
```

2026-10-16の直近検証は全284件成功・DB10件skip。
比較スクリプトは2回実行し、CSVが毎回15行になり、表示した集計と一致することを確認した。
計測値そのものを固定値で比較する自動テストは追加していない。

## PostgreSQLへの非同期一括保存

保存処理は[async_storage.py](../../src/myproj/persistence/async_storage.py)、
Queueと保存処理の接続は[async_collector.py](../../src/myproj/collection/async_collector.py)に実装する。
アラート判定用のrun_pipelineとは別のパイプラインである。

```text
デバイス別produce → Queue(maxsize=2) → consume_to_db → PostgreSQL
                                         ↓
                               指定件数・保存期限・Noneで保存
```

- `insert_telemetry_async(conn, message)`は新規挿入ならTrue、重複ならFalseを返す。
- `insert_telemetry_batch_async(conn, messages)`は1バッチを1つのtransactionで保存し、
  実際の挿入件数を返す。重複判定キーはdevice_id・event_time・sequence_no。
- `consume_to_db(queue, conn, batch_size=3, flush_interval=1.0)`は件数到達・期限到達・
  Noneの受信で保存する。保存成功後にバッファを空にし、実際の挿入件数を合計して返す。
- `run_db_pipeline(groups, conn, delay=0, batch_size=3, flush_interval=1.0)`は既存のproduceを使い、
  外側のTaskGroupでconsumer、内側でデバイスごとのproducerを管理する。
  全producer終了後にNoneを1回だけ送り、joinとタスク終了を待って挿入件数を返す。
- batch_sizeが1未満、またはflush_intervalが正の有限値でなければValueError。
  consumerとpipelineの両方で検証し、pipelineではTaskGroup開始前に例外を返す。
  DB接続の作成・終了は呼び出し側が担当し、1つのconsumerだけがその接続を使う。

保存の成功はconsumerの正常終了と戻り値で確認する。
`task_done()`は、項目を保存待ちリストに追加した段階でも呼ばれる。
`queue.join()`だけではDBへの保存成功を保証しない。

### 時間による保存

flush_intervalの単位は秒、既定値は1.0。
consumerが最初の1件を保存待ちリストへ追加した時点で、
`loop.time() + flush_interval`を期限にする。後続メッセージの受信では期限を延長しない。
Telemetryのevent_timeではなく、イベントループの単調増加する時計を使う。

| 経過時間 | 例: batch_size=3、flush_interval=1.0 |
|---|---|
| 0.0秒 | 1件目を保持し、期限を1.0秒に設定 |
| 0.6秒 | 2件目を保持。期限は変更しない |
| 1.0秒以降 | 次の受信待ちが期限に達し、保持している2件を保存 |

保存待ちがある間は、期限までの残り時間を指定してqueue.getをwait_forで待つ。
待機がタイムアウトしたら保存し、バッファと期限をリセットして受信を続ける。
時間切れは終了通知ではない。空の間は通常のqueue.getで待ち、空バッチは保存しない。
件数到達時にも期限をリセットし、次の保存待ちの1件目から新しい期限を設定する。

flush_intervalは保存を開始する目安であり、DB処理やイベントループの混雑も含めた
保存完了時間の上限ではない。たとえば0.1秒にする場合は、呼び出し側で指定する。

```python
inserted = await run_db_pipeline(
    groups, conn, batch_size=3, flush_interval=0.1
)
```

TimeoutErrorを捕捉するのはQueueの待機だけ。
DB保存自体がTimeoutErrorを出した場合は、そのまま呼び出し側へ伝える。
待機がタイムアウトした際は項目を取り出していないのでtask_doneを呼ばない。

### トランザクションと異常終了

検証ではautocommit=Trueの接続を使い、各バッチのtransactionを独立して確定する。
正常3件の保存後、次の2件で制約違反が起きた場合、後ろの2件だけが取り消され、
最初の3件は残る。パイプライン全体をまとめて取り消す仕組みではない。
呼び出し側が外側のtransactionを用意した場合は、その確定・取り消しにも従う。

DB consumerの失敗はTaskGroupからExceptionGroupとして伝わり、実行中のproducerも
キャンセルされる。外部からのキャンセルでは両タスクの終了を待ち、CancelledErrorを伝える。
キャンセル時のバッファ保存や再試行は行わず、未保存データの保持は保証しない。
異常終了時にQueueへ未取得の項目が残る場合、別途joinだけを待っても完了しない。

### 実DBテストの再現

[DBの準備手順](storage.md)に従い、ローカルPostgreSQLへの接続を用意する。
各DBテストは接続専用の一時テーブルとsearch_path=pg_tempを使い、通常の保存テーブルは変更しない。
接続の生成・利用・終了は同じasyncio.run内で行う。

```bash
# DBを使わず、consumerの件数・時間保存とタスクの異常終了を検証する（22件）
.venv/bin/python -m pytest -q tests/units/collection/test_async_collector.py

# 接続先を指定し、非同期保存とパイプラインを一時テーブルで検証する（12件）
TMRP_TEST_DSN='host=/var/run/postgresql port=5432 dbname=tmrp_dev user=shou' \
  .venv/bin/python -m pytest -q \
  tests/integration/persistence/test_async_storage.py \
  tests/integration/collection/test_async_collector_integration.py

# 自動整形・lint・本体の型検査・実DBを含む全テストを実行する
bash scripts/dev/check_test.sh --db
```

| テストファイル | ケース数 | 確認する内容 |
|---|---:|---|
| test_async_storage.py | 5 | 単件・一括保存、重複、空入力、バッチ全体のロールバック |
| test_async_collector.py | 22 | 件数・時間保存、空入力、間隔の検証、期限の維持、例外、キャンセル |
| test_async_collector_integration.py | 7 | 保存と再投入、ロールバック、複数producer、空入力、終了通知前の時間保存 |

結合テストの固定JSONLは2台・8件。初回の挿入件数は8、同じ入力の再実行では0となり、
DBの保存内容は変わらない。比較にはORDER BY device_id, sequence_noを指定し、
期待値にも同じ順序を適用する。

保存失敗の単体テストでは本物のconsumerと例外を出す保存モックを使う。
外部キャンセルの単体テストではEventで両タスクの開始を確認し、
本物のconsumerが空Queueで待機中にキャンセルされて終了することを確認する。
実DB書き込み中のキャンセルは、このテストの検証範囲に含まない。

時間保存の単体テストでは、実時計を変更せずconsumerが参照する時計を差し替えて、
後続受信で期限が延びないことを検証する。保存由来のTimeoutErrorは例外の同一性も確認し、
テスト自体の待機上限によるタイムアウトと区別する。

実DBでは、保存関数がtransactionを抜けた後のEvent通知を待ち、Noneを送る前に
1件ずつ2回の保存と全項目を確認する。別のケースでは件数未達の2件を時間保存し、
後ろの1件の制約違反によって正常な1件目も取り消され、0行になることを確認する。
これらは一時テーブルを使い、テスト側の手動rollbackには依存しない。

2026-10-20の検証結果: DBありは全328件成功、DB設定なしは306件成功・22件skip。
Ruff・46ファイルの書式検査・本体19ファイルのmypyも成功した。

## 次に接続する範囲

現在は、メモリに読み込んだTelemetryをアラート判定または非同期DB保存へ渡す構成である。
Queueの上限は待機中の項目数を制限するが、入力リストはメモリに保持する。
アラート用パイプラインは出力イベントリストも保持する。
非同期DB consumerは件数・時間・Noneで保存する。既存の同期MQTT Collectorには
今回のflush_intervalは適用されない。
MQTT購読との非同期接続、実通信・実DBでの性能比較、異常終了時の再試行・データ保持は今後の課題。
既存のMQTT Collectorは引き続き[従来の受信処理](mqtt.md)を使用する。
