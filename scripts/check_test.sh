#!/usr/bin/env bash

#set -e if check failed, exit immediately
#set -u if variable is not set, exit immediately
#set -o pipefail if any command in a pipeline fails, exit immediately
set -euo pipefail

use_db=false

case "${1:-}" in
    "")
        ;;
    --db)
        use_db=true
        ;;
    -h|--help)
        echo "Usage: $0 [--db]"
        echo " --db    Use the database for tests"
        exit 0
        ;;
    *)
        echo "Unknown option: $1" >&2
        echo "Usage: $0 [--db]" >&2
        exit 1
        ;;
esac

if (( $# > 1 )); then
    echo "Usage: $0 [--db]" >&2
    exit 1
fi

python=".venv/bin/python"

# Change to the root of the repository
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."

echo "Running code quality checks, formatting checks, and tests..."
# インポート順序を自動修正する
$python -m ruff check --select I --fix src tests

# 改行や空白などを整形する
$python -m ruff format src tests

# 整形後にコード規約を確認する
$python -m ruff check src tests
echo "Code quality checks passed."

# 書式が整っていることを確認する
$python -m ruff format --check src tests
echo "Code formatting checks passed."

# run static type checks
$python -m mypy

# Run test
if [[ "$use_db" == true ]]; then
    echo "Running tests with the test database..."
    TMRP_TEST_DSN='host=/var/run/postgresql port=5432 dbname=tmrp_dev user=shou' \
        $python -m pytest -q
else
    $python -m pytest -q
fi