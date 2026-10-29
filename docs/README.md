# 文書一覧

## 開発手順

- [プロジェクト構成とファイルの置き場所](development/project-structure.md)
- [導入後の検証手順](development/verification.md)
- [電力受信サーバーの検証結果](development/power-receiver-verification.md)
- [受信サーバーの性能試験条件・合格基準](development/power-performance-plan.md)
- [受信サーバーの性能実測結果（2026-10-29）](development/power-performance-results-20261029.md)

## 仕様

- [Telemetryのデータ契約](reference/telemetry-contract.md)
- [電力Telemetryのデータ契約・仮台帳・サンプル（P1）](reference/power-telemetry-contract.md)
- [監視対象の用語集](../CONTEXT.md)
- [設定とログ出力](reference/configuration.md)

## 利用ガイド

- [データ分析・可視化](guides/analysis.md)
- [MQTTの送受信](guides/mqtt.md)
- [非同期MQTT購読とDB保存](guides/async-mqtt.md)
- [電力遥測受信サーバーの仕様・起動・systemd配備](guides/power-receiver.md)
- [サーバー起動スクリプトと電力データの継続送信](guides/power-simulator.md)
- [PostgreSQLへの保存](guides/storage.md)
- [低バッテリーアラート](guides/alerts.md)
- [非同期パイプライン・DB保存・比較実験](guides/async-pipeline.md)
