# アプリケーション設定

## 目的と現在の機能

アプリの実行環境とログレベルをUTF-8のJSONファイルで指定する。
`tmrp check-config <path>` はファイルを読み込み、設定を検証して値を表示する。
`tmrp validate <path> --config <config-path>` は設定の `log_level` を適用し、Telemetryの検証結果をJSONログで記録する。
`--config` を省略した場合は、従来どおり標準出力へ成功結果、標準エラーへ通常のエラー文を出力する。

## 設定項目

| 項目 | 型 | 省略時 | 許可する値 |
|---|---|---|---|
| `environment` | 文字列 | 必須のためエラー | `development`、`test`、`production` |
| `log_level` | 文字列 | `"INFO"` | `DEBUG`、`INFO`、`WARNING`、`ERROR`、`CRITICAL` |

- 最上位はJSONオブジェクトとする。
- 未知のキーは拒否する。
- `null`・空文字・文字列以外の値は、どちらの項目でも拒否する。
- `log_level` の既定値はキーが省略された場合だけ使う。
- 大文字・小文字を区別し、自動変換しない。

[正常サンプル](../examples/config/valid.json):

```json
{
  "environment": "development",
  "log_level": "INFO"
}
```

次のように `log_level` を省略しても有効で、値は `"INFO"` になる。

```json
{
  "environment": "development"
}
```

`"log_level": null` や `"log_level": ""` は省略とは異なり、エラーになる。

## 実行方法

READMEのセットアップを完了し、仮想環境を有効にした状態で、TMRPディレクトリから実行する。
相対パスはコマンドを実行したディレクトリを基準に解釈される。

### 正常な設定

```bash
# 設定ファイルを検証して、採用された値を表示する
tmrp check-config examples/config/valid.json

# 直前の終了コードを表示する。期待値は0
echo $?
```

標準出力:

```text
environment=development log_level=INFO
```

標準エラーには何も出力しない。

### 不正な設定値

```bash
# 許可されていないログレベルVERBOSEを含む設定を検証する
tmrp check-config examples/config/invalid/invalid-log-level.json

# 直前の終了コードを表示する。期待値は1
echo $?
```

標準エラー:

```text
Error: The 'log_level' field must be one of 'DEBUG', 'INFO', 'WARNING', 'ERROR', or 'CRITICAL'. Received: VERBOSE
```

標準出力は空になる。ほかの異常サンプルも終了コード1になる。

| サンプル | 拒否する理由 |
|---|---|
| [missing-environment.json](../examples/config/invalid/missing-environment.json) | 必須の `environment` がない |
| [unknown-field.json](../examples/config/invalid/unknown-field.json) | 未知のキー `debug` がある |

### パス引数の不足

```bash
# 必須のパス引数を省略し、引数エラーを確認する
tmrp check-config

# 直前の終了コードを表示する。期待値は2
echo $?
```

標準エラーに使用方法と、`path` が必要である旨を表示する。標準出力は空になる。

## check-configの終了コードとエラー

| 終了コード | 意味 | 出力先 |
|---|---|---|
| `0` | 設定の読み込みと検証に成功 | 標準出力に設定値 |
| `1` | ファイル読み込み・文字コード・JSON構文・設定値のエラー | 標準エラーに `Error: ...` |
| `2` | 引数不足など、CLIの使い方のエラー | 標準エラーに使用方法とエラー |

ファイル不存在、ディレクトリの指定、UTF-8として読めない内容、壊れたJSONは読み込みエラーとして扱い、メッセージに対象パスと原因を含める。
設定値の検証エラーは、問題のある項目や入力形式を説明する。
これらの想定されたエラーでは、CLIはトレースバックを表示しない。

## Telemetry検証とJSONログ

`validate` の位置引数はTelemetryのJSONファイル、`--config` の引数はアプリの設定ファイルを指定する。
設定の読み込み・検証が成功してから、Telemetryの読み込みと検証を行う。

### 正常時の出力

```bash
# INFO設定でTelemetryを検証する
# 標準出力には検証結果、標準エラーにはINFOのJSONログが1行出る
tmrp validate examples/telemetry/valid.json --config examples/config/valid.json

# 直前の終了コードを表示する。期待値は0
echo $?
```

標準出力:

```text
device_id=robot-001 sequence_no=1001 event_time=2024-06-01T12:00:00+00:00
```

標準エラーの例（`timestamp` はログを生成した時刻なので実行ごとに変わる）:

```json
{"level": "INFO", "logger": "myproj", "message": "device_id=robot-001 sequence_no=1001 event_time=2024-06-01T12:00:00+00:00", "timestamp": "2026-10-03T00:00:00+00:00"}
```

### 異常時の出力

```bash
# device_idが欠けたTelemetryをINFO設定で検証する
# 標準出力は空で、標準エラーへERRORのJSONログが1行出る
tmrp validate examples/telemetry/invalid/missing-device-id.json --config examples/config/valid.json

# 直前の終了コードを表示する。期待値は1
echo $?
```

JSONの `message` に拒否理由と `device_id` が含まれる。
通常のエラー文とJSONログを重複して出力しない。

設定ファイル自体の読み込み・検証に失敗した場合は、loggingの初期化前に処理を終了する。
その場合は標準エラーに通常の `Error: ...` を表示し、終了コード1を返す。Telemetryは検証しない。

### ログレベル

`log_level` は出力するログの最低レベルを指定する。
現在の `validate` は成功をINFO、Telemetryの読み込み・検証失敗をERRORで記録する。

| 設定値 | 成功時のINFOログ | 失敗時のERRORログ |
|---|---|---|
| `DEBUG`・`INFO` | 出力する | 出力する |
| `WARNING`・`ERROR` | 出力しない | 出力する |
| `CRITICAL` | 出力しない | 出力しない |

例えば、設定ファイルの `log_level` を `"WARNING"` にすると、成功時の標準エラーは空になる。
ログを抑制しても、成功結果の標準出力や終了コードは変わらない。
`CRITICAL` では検証失敗時のログも抑制されるため、成否は終了コードで判定する。
設定ファイル自体のエラー表示と、引数エラーの表示には、このフィルタは適用されない。

### JSONログの項目

| 項目 | 意味 |
|---|---|
| `timestamp` | ログ生成時刻。UTCのISO 8601形式。Telemetryの `event_time` とは別の時刻 |
| `level` | `INFO`、`ERROR` などのログレベル |
| `logger` | 発生元のLogger名。CLIでは `myproj` |
| `message` | 正常時はdevice ID・連番・イベント時刻、異常時は原因を説明する文字列 |

ログ1件はJSONオブジェクト1行で出力する。日本語はそのまま残し、メッセージ内の改行はJSONとしてエスケープする。
現在のdevice IDや連番は `message` 内の文字列であり、独立したJSON項目ではない。

### validateの終了コード

| 終了コード | 意味 |
|---|---|
| `0` | Telemetryの検証に成功 |
| `1` | 設定またはTelemetryの読み込み・検証に失敗 |
| `2` | 入力パスや `--config` の値がないなど、CLI引数が不正 |

## 開発時の確認

```bash
# 設定モデル・ローダー・JSONログ・CLIのテストを実行する
.venv/bin/python -m pytest tests/units/test_config.py tests/units/test_logging_config.py tests/units/test_cli.py -q

# インポート順序と書式を自動修正し、lint・型チェック・全テストを実行する
bash scripts/check_test.sh
```

Python APIの `load_config(path: Path) -> AppConfig` は、読み込み失敗を `ConfigLoadError` に変換し、`raise ... from e` で原因を保持する。
設定値の不正は `ConfigValidationError` として伝える。CLIがこれらを表示と終了コードへ変換する。
