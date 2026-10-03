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
| `enqueue` | 布尔值 | `false` | `true` 开启文件与标准错误的后台队列写入；空值关闭 |
| `log_file` | オブジェクト | ファイル出力なし | 下記のファイル出力設定を参照 |
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
| `logger` | アプリがログに付ける名前。CLIでは `myproj` |
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


## Loguruによる実装

ログ出力にはLoguruを使用する。`pyproject.toml`の実行時依存関係に登録しているため、
READMEの `python -m pip install -e ".[dev]"` で一緒にインストールされる。

`configure_logging(config)` はLoguruの既存の出力先を取り除き、指定レベルのJSON標準エラー出力と、設定された場合はファイル出力を登録する。
この関数がアプリ全体のLoguru出力先を管理するため、個別のモジュールで出力先を追加する必要はない。
戻り値のLoggerには `bind(logger="myproj")` でログ上の名前を付ける。
再設定しても同じログは重複しない。

```python
from myproj.config import AppConfig
from myproj.logging_config import configure_logging

logger = configure_logging(AppConfig(environment="development", log_level="INFO"))
logger.info("設定を読み込みました: {}", "config.json")
```

Loguruの引数展開は `{}` を使う。標準loggingで使った `%s` は置き換える。
既存の4項目のJSON形式を維持するため、共通のformat関数でLoguruのレコードをJSONへ変換している。
標準loggingの `JsonFormatter` はこのsinkに置き換わった。

参考: [Loguru API](https://loguru.readthedocs.io/en/stable/api/logger.html)、
[独自のJSON変換を行う公式レシピ](https://loguru.readthedocs.io/en/stable/resources/recipes.html#serializing-log-messages-using-a-custom-function)。


## 文件日志配置与全局使用

### 只初始化一次

Loguru 提供进程内共享的 logger。程序入口读取配置并调用一次
`configure_logging(config)`，随后所有模块直接导入 `loguru.logger` 即可。
`bind()` 创建带上下文的 logger，仍共享相同输出配置，不会重新读配置或创建日志文件。
不要在每个模块调用 `configure_logging()`：该函数用于启动或主动重新配置，会移除已有输出。
多个独立进程需分别初始化；本功能面向单进程、多线程使用。

入口 `main.py`：

```python
from pathlib import Path
from myproj.config import load_config
from myproj.logging_config import configure_logging
from worker import run

logger = configure_logging(load_config(Path("examples/config/file-logging.json")))
logger.info("程序启动")
run()
```

其他模块 `worker.py`：

```python
from loguru import logger

worker_logger = logger.bind(logger="worker")

def run():
    worker_logger.info("处理任务：{}", "task-001")
```

### 完整配置示例

可运行示例：[file-logging.json](../examples/config/file-logging.json)。

```json
{
  "environment": "development",
  "log_level": "INFO",
  "enqueue": true,
  "log_file": {
    "path": "logs/app_{time:YYYY-MM-DD_HH-mm-ss}.jsonl",
    "max_bytes": 10485760,
    "rotation_interval_seconds": 3600,
    "rotation_time": "00:00",
    "cleanup_days": 7,
    "compression": "zip",
    "delay": false
  }
}
```

| 配置项 | 默认值 | 含义 |
|---|---|---|
| `path` | 必填 | 文件路径；相对路径基于当前工作目录，父目录自动创建。支持 `{time:YYYY-MM-DD_HH-mm-ss}` 文件名时间模板 |
| `max_bytes` | `null` | 正整数，当前文件加上新日志超过此字节数时轮转。例如 10485760 为 10 MiB |
| `rotation_interval_seconds` | `null` | 正整数，从初始化或上次轮转起经过多少秒创建新文件 |
| `rotation_time` | `null` | 每日轮转时间，严格使用 `HH:MM`，例如 `00:00` 或 `03:30`，采用运行机器的本地时区 |
| `cleanup_days` | `null` | 正整数，删除修改时间早于指定天数的日志归档，包括压缩归档 |
| `compression` | `null` | 归档压缩格式：`zip`、`gz`、`bz2`、`xz`；`null` 表示不压缩 |
| `delay` | `false` | `false` 在初始化时创建文件；`true` 延迟到第一条符合日志级别的日志才创建 |

省略整个 `log_file` 时只输出标准错误。提供它时必须是对象；未知字段、空路径、
非正整数、无效时间及压缩格式会在读取配置时拒绝。大小、轮转间隔、每日轮转时间、保留天数和压缩格式的字段省略、`null`、
空字符串 `""` 或纯空白字符串均表示关闭对应功能。`delay` 同样接受空值，
按 `false` 处理，即关闭延迟创建；非空值必须是布尔值。
所有这些选项为空时，日志仍写入 `path` 指定的文件，但不轮转、不清理、不压缩。
`path` 仍必须是非空路径；数字 `0` 和负数属于无效参数，会报错。

大小、间隔、每日时间可以同时配置，任意一个条件满足就轮转。
只需按大小轮转时，省略两个时间字段；只需每日轮转时，省略大小和间隔字段。
无轮转条件时持续追加同一文件。已有文件默认追加，不覆盖。
固定路径如 `logs/app.jsonl` 会由 Loguru 自动给旧文件添加时间后缀，避免覆盖归档。
单条日志不拆分，因此单条日志大于大小上限时，文件仍可能超过该上限。

轮转检查发生在写入日志之前，不启动后台定时器。每日时间或间隔到达后，
下一条符合级别的日志触发创建新文件。时间模板使用实际文件创建时间；
JSON 中的 `timestamp` 仍使用 UTC。

`cleanup_days` 是保留期限，不是每隔几天运行一次清理的周期。
有轮转策略时，Loguru 在轮转时压缩并清理旧文件；没有轮转策略时，在输出关闭时执行。
程序退出或调用 `logger.remove()` 会关闭输出。空闲时不会自动清理；
若需要无日志时也在固定时间清理，应使用外部定时任务。
清理仅针对该文件路径模板匹配的文件，因此请为此 logger 使用专用文件名。

文件与标准错误输出使用相同日志级别和四字段 JSON Lines 格式，中文直接保留。
默认立即创建文件时，路径权限等初始化错误由 CLI 显示为普通错误并返回 1；
延迟创建模式下的路径错误发生在第一条日志写入时。

### 命令行使用

在 TMRP 目录中执行：

```bash
# 验证配置，不创建日志文件
.venv/bin/tmrp check-config examples/config/file-logging.json

# 标准错误和日志文件中同时记录验证结果
.venv/bin/tmrp validate examples/telemetry/valid.json --config examples/config/file-logging.json
```

实现采用 [Loguru 的文件 sink、轮转、保留和压缩接口](https://loguru.readthedocs.io/en/stable/api/logger.html)。


### 异步日志（后台队列写入）

在 JSON 最上层添加 `"enqueue": true`，同时开启文件和标准错误的后台队列写入。
省略、`false`、`null`、`""` 或纯空白字符串均关闭异步，保持同步输出。
非空值只接受 JSON 布尔值；`"true"` 和 `1` 会报配置错误。
即使不配置文件输出，该选项也可用于标准错误输出。

业务代码仍使用 `logger.info()` 等普通调用，无需 `await`。日志格式化和入队在调用线程完成，
实际写入由后台线程执行；它减少业务等待磁盘的时间，但不保证调用完全不阻塞。
后台写入错误不能作为异常返回给原来的业务调用，会由 Loguru 报告到标准错误。

程序结束前使用 `finally` 等待已入队日志写完：

```python
from pathlib import Path
from myproj.config import load_config
from myproj.logging_config import configure_logging

logger = configure_logging(load_config(Path("examples/config/file-logging.json")))
try:
    logger.info("程序启动")
    # 执行业务逻辑
finally:
    logger.complete()
```

`logger.complete()` 等待队列写完，不关闭输出。需要关闭输出时使用 `logger.remove()`。
CLI 的 `validate` 已在成功及失败返回前自动等待队列完成。
异步模式继续支持原有轮转、清理、压缩和全局复用。
参考：[Loguru enqueue 与 complete API](https://loguru.readthedocs.io/en/stable/api/logger.html)。
