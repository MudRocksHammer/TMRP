# Config Contract

## Purpose
System Running config

|             | 型     | 省略時 | 許可する値                            |
| ----------- | ------ | ------ | ------------------------------------- |
| environment | 文字列 | エラー | development, test, production         |
| log_level   | 文字列 | "INFO" | DEBUG, INFO, WARNING, ERROR, CRITICAL |

- 最上位はJSONオブジェクト。
- 未知のキーは拒否する。
- null は拒否する。log_level の既定値は、キーが省略された場合だけ使う。
- 大文字・小文字を区別し、自動変換しない。