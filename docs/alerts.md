# 低バッテリーアラートとCSVレポート

Week 8では、デバイス別の状態を保持し、低残量の発生・復帰時だけ根拠付きイベントを生成する。
実装は[src/myproj/alerts.py](../src/myproj/alerts.py)、再現用スクリプトは
[scripts/report_battery_alerts.py](../scripts/report_battery_alerts.py)にある。

## 判定ルール

`UNKNOWN`は有効な測定値でまだ判定していない状態、`NORMAL`は通常、`LOW`は低残量を表す。
入力はTelemetryMessageで検証済みの0〜100の値、または欠損値を前提とする。

| 現在の状態 | battery_percent | 次の状態 | イベント |
|---|---|---|---|
| すべて | None | 現在の状態を維持 | なし |
| UNKNOWN | 20以下 | LOW | triggered |
| UNKNOWN | 20超 | NORMAL | なし |
| NORMAL | 20以下 | LOW | triggered |
| NORMAL | 20超 | NORMAL | なし |
| LOW | 25未満 | LOW | なし |
| LOW | 25以上 | NORMAL | recovered |

発生と復帰の閾値を分け、20付近の小さな変動でイベントが繰り返されることを抑える。
例えばLOWの後に24.9が来ても復帰せず、25で復帰する。初回の24.9はNORMALとなる。
欠損時に残る状態は最後の判定であり、現在の測定値が取得できたことを意味しない。

`BatteryAlertMonitor`はデバイスごとの状態をインスタンス内の辞書で管理する。
同じ状態が続く間はイベントを出さない。初回のLOWは発生として扱い、初回のNORMALは復帰としない。
イベントにはkind、device_id、sequence_no、event_time、battery_percentを保存する。
時刻と測定値は、処理した入力メッセージから引き継ぐ。

## 再現手順

READMEの手順で本体と開発用依存関係をインストールし、TMRPのルートで実行する。
この処理はMQTT・PostgreSQL・分析用の追加依存関係を使わない。

```bash
# 固定JSONLを読み、低残量の発生・復帰イベントをCSVへ保存する
.venv/bin/python scripts/report_battery_alerts.py

# ヘッダーと5件のイベントを確認する
cat reports/battery_alerts.csv
```

入力は[examples/telemetry/battery_alerts.jsonl](../examples/telemetry/battery_alerts.jsonl)の8件。
2デバイスのデータをファイルの行順に処理する。Monitorはファイル全体で1個だけ使う。
出力フォルダーを自動作成し、CSVはUTF-8で毎回上書きする。標準出力には生成したイベントも表示する。

出力は[reports/battery_alerts.csv](../reports/battery_alerts.csv)。期待結果は次のとおり。
既存の分析レポートと同様、この固定入力から生成したCSVも再現例としてGitで管理する。

```csv
kind,device_id,sequence_no,event_time,battery_percent
triggered,robot-002,1,2024-06-01T12:01:00+00:00,20
triggered,robot-001,2,2024-06-01T12:02:00+00:00,20
recovered,robot-002,2,2024-06-01T12:05:00+00:00,25
recovered,robot-001,5,2024-06-01T12:06:00+00:00,25
triggered,robot-001,6,2024-06-01T12:07:00+00:00,20
```

再実行してもヘッダー1行とイベント5件になる。空入力ではヘッダーだけを出力する。
kindはEnumのvalue、event_timeはタイムゾーン付きのisoformatで出力する。
このサンプルの時刻はUTC。任意の入力に対してUTCへ変換する処理はレポート側では行っていない。

## 自動テストと検査

```bash
# 状態遷移14件、Monitor5件、CSVレポート3件を検証する（DB不要）
.venv/bin/python -m pytest -q tests/units/test_alerts.py tests/units/test_alert_monitor.py tests/integration/test_battery_report.py

# DB接続設定を除き、自動整形・lint・型・全テストを実行する
# DBを必要とする10件はskipし、CSVレポートのテストは実行する
env -u TMRP_TEST_DSN bash scripts/check_test.sh

# srcとレポートスクリプトを合わせて型検査する
.venv/bin/python -m mypy src scripts/report_battery_alerts.py

# 設定済みのローカル学習用DBを含めて品質検査と全テストを実行する
bash scripts/check_test.sh --db
```

品質検査スクリプトのRuff対象はsrc/tests/scripts、mypy対象はsrc。
レポートスクリプトの型検査は上記の追加コマンドで行う。
`--db`の接続先と一時テーブルによる検証は[ストレージの手順](storage.md#検査スクリプトの使い方)を参照する。

CSVテストは一時フォルダーへ入力をコピーし、スクリプトのPROJECT_ROOTを差し替える。
全項目・順序、再実行時のCSV行の一致、空入力を確認し、実際のレポートファイルは変更しない。
2026-10-14の検証では、DB統合10件を含む全287件が成功した。
一時コピーに追記モード、Enum直接出力、時刻直接出力、フォルダー作成漏れを個別に戻し、
追加テストがすべての不具合を検出することも確認した。

## 現在の範囲

同一デバイスの入力は時刻順を前提とし、ファイルの並べ替えや過去データの重複排除は行わない。
状態はメモリ内に保持し、スクリプトを再実行すると初期化する。
MQTT Collectorへの組み込み、アラートのDB保存、通知、状態の永続化は今後の課題。
温度・RSSIのアラート判定は含まない。
