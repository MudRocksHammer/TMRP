# 電力Telemetryのデータ契約（P1）

状態: 学習用の契約初稿。本体・テストはこれから実装する。旧TelemetryMessageとは別のPowerTelemetryを追加する。

## 対象と台帳

日産6万トンの露天炭鉱にある給電12回線・変電所4か所を題材とする。現場を制御する契約ではなく、監視・記録用の観測を定義する。

[仮台帳](../../examples/power/assets.json)には4変電所、12回線、12監視機器を定義した。各変電所3機器という所属は学習用の仮定で、実際の結線や運用電圧を示さない。サンプルの10000 V等も試験値である。

変電所・回線・監視機器は別の概念。[用語集](../../CONTEXT.md)を参照する。メッセージにはdevice_idだけを入れ、line_idとsubstation_idは台帳から参照する。これにより同じ所属情報の食い違いを避ける。

P1のモデルは台帳を読み込まずdevice_idの文字列形式だけを検証する。未登録機器の拒否、Topicとの一致、時点ごとの所属管理は受信処理の後続課題とする。

## 必須の共通項目

全16キーがJSONに必要。未知のキーは拒否する。nullを許すのは下記8測定項目だけ。

| 項目 | JSONの型 | Pythonモデルの型 | 規則 |
|---|---|---|---|
| schema_version | string | str | "1.0"固定 |
| message_type | string | str | "power_telemetry"固定 |
| device_id | string | str | 空・空白のみ・前後空白を拒否。自動stripしない |
| boot_id | string | str | 同上。起動セッションを識別する |
| sequence_no | integer | int | 0以上、boolと小数を拒否 |
| event_time | string | datetime | ISO 8601、タイムゾーン必須。内部はUTCへ正規化 |
| breaker_state | string | BreakerState | "open" / "closed" / "unknown" |
| quality | string | MeasurementQuality | "good" / "partial" / "unavailable" |

`event_time`は観測時刻で、サーバー受信時刻ではない。オフセット付き日時を受け付け、JSON出力時はUTCのISO 8601とする。`Z`と`+00:00`は同じ時刻。受信時刻は後段で追加する。

### 遮断器状態

- open: 開いていると観測した。
- closed: 閉じていると観測した。
- unknown: 状態を取得できない／確定できない。

トリップは動作イベントであり、現在の開閉状態とは別。`tripped`はこのEnumへ加えない。openだから電圧ゼロ等の物理的整合性はP1で推定・検証しない。

## 測定項目と単位

| 項目 | 意味 | 値の規則 |
|---|---|---|
| voltage_ab_v | A-B線間電圧の実効値、V | 有限の数値、0以上、またはnull |
| voltage_bc_v | B-C線間電圧の実効値、V | 同上 |
| voltage_ca_v | C-A線間電圧の実効値、V | 同上 |
| current_a_a | A相電流の実効値、A | 同上 |
| current_b_a | B相電流の実効値、A | 同上 |
| current_c_a | C相電流の実効値、A | 同上 |
| active_power_kw | 三相合計の有効電力、kW | 有限の数値、負値を含む、またはnull |
| frequency_hz | 周波数、Hz | 有限の数値、0以上、またはnull |

有効電力の正方向は当該監視点で定義した供給側→負荷側、負は逆方向とする。実際の向きは設置時に対応付ける。サンプルだけから鉱区全体の給電方向を推定しない。

- Pythonの型は8項目とも`float | None`。有限のint/float入力を受け付けるが、boolは拒否する。検証後の数値はfloatへ正規化する。
- 数値文字列、NaN、正負のInfinityを拒否する。数値文字列を自動変換しない。
- floatへ変換できないほど巨大な整数も検証エラーにする。
- 0は取得済みの観測値。nullは取得できなかった項目で、0に補完しない。
- 全8キーを必要とし、値が欠損している場合はnullを明示する。キー自体がない場合は契約違反。
- 形式検証では運転限界や警報閾値を設定しない。上限を勝手に追加せず、別の警報ルールとして後で扱う。

## qualityと欠損の対応

qualityは8測定値の取得可否だけを表す。遮断器状態の取得可否はbreaker_stateで表す。

| quality | 8測定値の条件 |
|---|---|
| good | 8項目すべて数値 |
| partial | nullが1〜7項目 |
| unavailable | 8項目すべてnull |

goodは設備が正常・安全という意味ではない。品質とnullの個数が食い違う入力は拒否する。unavailableは構造上有効なメッセージなので、必ずしも入力エラーではない。何も届かない通信断とは区別する。

## 再送と起動セッション

メッセージの識別キーは`(device_id, boot_id, sequence_no)`とする。

- 新しい起動セッションでは新しいboot_idを発行し、sequence_noは0から始められる。
- 同じセッション内では観測ごとにsequence_noを増やす。同一機器のboot_idを別の起動で再利用しない。
- 通信再接続や未送信データの再送では既存のboot_id・sequence_no・観測内容を保持する。
- サンプルのboot_idは読みやすい固定値。P2の送信器では新セッションにUUID等で一意な値を生成する。P1ではUUID形式を要求しない。
- event_timeは識別キーへ含めない。時刻や値を変えて同じキーを使った場合は後段で内容の衝突として扱う。

P1は単件モデルなので連番の履歴や起動IDの使い回しを検出しない。永続保存での重複・衝突検出はP3。

## Python側の実装範囲

配置: `src/myproj/telemetry/power.py`。

- `PowerTelemetryValidationError(ValueError)`
- `BreakerState(Enum)`: OPEN="open"、CLOSED="closed"、UNKNOWN="unknown"
- `MeasurementQuality(Enum)`: GOOD="good"、PARTIAL="partial"、UNAVAILABLE="unavailable"
- `@dataclass class PowerTelemetry`: 上記16項目。全フィールド必須、既定値なし。

直接コンストラクターにはdatetimeとEnumインスタンスを渡す。生の文字列のEnumや時刻は拒否する。共通項目→8測定値→品質整合性の順で検証する。型注釈だけでは入力検証にならないので、`__post_init__`でも確認する。

`__post_init__`ではaware datetimeをUTCへ正規化し、数値をfloatへ正規化する。検証失敗はPowerTelemetryValidationErrorへそろえる。

P1-2は型・コンストラクター検証まで。P1-3で次の変換を追加する。

- `from_dict(data: object) -> Self`: 辞書、必須／未知キー、JSON側の型を確認してdatetime・Enumへ変換し、コンストラクターを呼ぶ。
- `from_json(text: str) -> Self`: JSON解析後にfrom_dictを呼ぶ。不正JSONも独自例外へそろえる。
- `to_dict() -> dict[str, object]`: Enumは値、日時はUTC文字列、null項目も含めて全16キーを出す。
- `to_json() -> str`: JSONを生成する。型・値・意味が往復で一致することをテストする。

既存のTelemetryMessage、MQTT入力処理、DBスキーマはこの段階で変更しない。

## サンプルと期待結果

| ファイル | 内容 | 期待 |
|---|---|---|
| [valid.json](../../examples/power/valid.json) | 全測定値あり、good | 受理 |
| [partial.json](../../examples/power/partial.json) | B相電流だけnull、partial | 受理 |
| [unavailable.json](../../examples/power/unavailable.json) | 全測定値null、unavailable | 受理 |
| [negative-current.json](../../examples/power/invalid/negative-current.json) | 負の実効電流 | 拒否 |
| [boolean-measurement.json](../../examples/power/invalid/boolean-measurement.json) | 数値の代わりにtrue | 拒否 |
| [boolean-sequence.json](../../examples/power/invalid/boolean-sequence.json) | sequence_noがtrue | 拒否 |
| [inconsistent-quality.json](../../examples/power/invalid/inconsistent-quality.json) | goodなのにnullあり | 拒否 |
| [missing-timezone.json](../../examples/power/invalid/missing-timezone.json) | タイムゾーンなし | 拒否 |
| [unknown-field.json](../../examples/power/invalid/unknown-field.json) | 未定義のvoltage_v | 拒否 |
| [invalid-breaker-state.json](../../examples/power/invalid/invalid-breaker-state.json) | trippedを状態に指定 | 拒否 |
| [missing-measurement-key.json](../../examples/power/invalid/missing-measurement-key.json) | current_b_aキーなし | 拒否 |

不正サンプルもJSON文法としては有効で、契約検証で拒否される。NaN・Infinityは有効なJSONサンプルにせず、Pythonのテストで生成して拒否を確認する。
