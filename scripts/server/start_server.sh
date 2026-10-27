#!/usr/bin/env bash
# エラー・未定義変数で停止し、最後はexecでサーバーへシグナルを直接渡す。
set -euo pipefail
project_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
python_bin="${TMRP_PYTHON:-$project_root/.venv/bin/python}"
config="$project_root/examples/power/receiver-local.toml"
initialize=false

while (( $# )); do
    case "$1" in
        --config)
            if (( $# < 2 )); then echo '--configにはファイルを指定してください。' >&2; exit 2; fi
            config="$2"
            shift 2
            ;;
        --init-db) initialize=true; shift ;;
        -h|--help)
            echo 'Usage: bash scripts/server/start_server.sh [--config PATH] [--init-db]'
            echo 'TMRP_RECEIVER_DSNが必要です。Broker・PostgreSQLは事前に起動してください。'
            echo '--init-db: 電力テーブルを初期化してから前景でサーバーを起動します。'
            exit 0
            ;;
        *) echo "未対応の引数: $1" >&2; exit 2 ;;
    esac
done

if [[ ! -x "$python_bin" ]]; then
    echo "Pythonが見つかりません: $python_bin" >&2
    exit 2
fi
if [[ -z "${TMRP_RECEIVER_DSN:-}" ]]; then
    echo 'TMRP_RECEIVER_DSNにPostgreSQL接続先を設定してください。' >&2
    exit 2
fi
# 実行場所に依存せず、このチェックアウトのソースを使用する。
export PYTHONPATH="$project_root/src${PYTHONPATH:+:$PYTHONPATH}"
"$python_bin" -m myproj.app.receiver --config "$config" --check-config
if [[ "$initialize" == true ]]; then
    "$python_bin" -m myproj.app.receiver --config "$config" --init-db
fi
exec "$python_bin" -m myproj.app.receiver --config "$config"
