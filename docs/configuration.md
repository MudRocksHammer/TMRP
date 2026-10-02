# アプリケーション設定

## 目的と現在の機能

アプリの実行環境とログレベルをUTF-8のJSONファイルで指定する。
`tmrp check-config <path>` はファイルを読み込み、設定を検証して値を表示する。
現在は検証と表示までを実装しており、`log_level` を実際のloggingへ適用する処理は今後追加する。

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
Error: The 'log_level' field must be one of 'DEBUG', 'INFO', 'WARNING', 'ERROR', or 'CRITICAL'.
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

## 終了コードとエラー

| 終了コード | 意味 | 出力先 |
|---|---|---|
| `0` | 設定の読み込みと検証に成功 | 標準出力に設定値 |
| `1` | ファイル読み込み・文字コード・JSON構文・設定値のエラー | 標準エラーに `Error: ...` |
| `2` | 引数不足など、CLIの使い方のエラー | 標準エラーに使用方法とエラー |

ファイル不存在、ディレクトリの指定、UTF-8として読めない内容、壊れたJSONは読み込みエラーとして扱い、メッセージに対象パスと原因を含める。
設定値の検証エラーは、問題のある項目や入力形式を説明する。
これらの想定されたエラーでは、CLIはトレースバックを表示しない。

## 開発時の確認

```bash
# 設定モデル・ローダー・CLIのテストを実行する
.venv/bin/python -m pytest tests/units/test_config.py tests/units/test_cli.py -q

# インポート順序と書式を自動修正し、lint・型チェック・全テストを実行する
bash scripts/check_test.sh
```

Python APIの `load_config(path: Path) -> AppConfig` は、読み込み失敗を `ConfigLoadError` に変換し、`raise ... from e` で原因を保持する。
設定値の不正は `ConfigValidationError` として伝える。CLIがこれらを表示と終了コードへ変換する。
