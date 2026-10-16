# asyncioによるTelemetry処理と比較実験

Week 9の基礎演習として、固定JSONLから読み込んだTelemetryに受信待ちを模した遅延を加え、
同期・非同期・Queue経由の3方式で同じアラートが得られることを確認する。

実装は[src/myproj/async_pipeline.py](../src/myproj/async_pipeline.py)、
比較スクリプトは[scripts/compare_async_telemetry.py](../scripts/compare_async_telemetry.py)。
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
.venv/bin/python scripts/compare_async_telemetry.py

# 保存した15回分の測定結果を確認する
cat reports/async_benchmark.csv
```

入力は[固定JSONL](../examples/telemetry/battery_alerts.jsonl)の8件。
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

全検証の成功後、[reports/async_benchmark.csv](../reports/async_benchmark.csv)を上書きする。
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

[tests/units/test_async_pipeline.py](../tests/units/test_async_pipeline.py)には7ケースがある。

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
.venv/bin/python -m pytest -q tests/units/test_async_pipeline.py

# DB設定を除いて、整形・lint・型・既存テスト全体を検査する
# DBを必要とする10件はskipする
env -u TMRP_TEST_DSN bash scripts/check_test.sh

# srcに加え、比較スクリプトとQueueテストも型検査する
.venv/bin/python -m mypy src scripts/compare_async_telemetry.py tests/units/test_async_pipeline.py
```

2026-10-16の直近検証は全284件成功・DB10件skip。
比較スクリプトは2回実行し、CSVが毎回15行になり、表示した集計と一致することを確認した。
計測値そのものを固定値で比較する自動テストは追加していない。

## 次に接続する範囲

現在は、メモリに読み込んだTelemetryを処理する基礎実装である。
Queueの上限は待機中の項目数を制限するが、入力リストと出力イベントリストはメモリに保持する。
MQTT購読、非同期DB保存、実通信での負荷測定、異常終了時の再試行・データ保持は今後の課題。
既存のMQTT Collectorは引き続き[従来の受信処理](mqtt.md)を使用する。
