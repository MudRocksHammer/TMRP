# 電力監視の学習用データ

仕様と各ファイルの期待結果は[電力Telemetry契約](../../docs/reference/power-telemetry-contract.md)を参照する。

- assets.json: 4変電所・12回線・12監視機器の仮台帳。実設備の結線図ではない。
- valid.json / partial.json / unavailable.json: 取得可否の異なる有効なメッセージ。
- invalid/: JSONとして読めるが電力データ契約に違反するメッセージ。

サンプル値・時刻・所属は試験用。現在のロボット用TelemetryMessage.from_jsonでは扱えない。
PowerTelemetryの変換処理を実装した後に使用する。
