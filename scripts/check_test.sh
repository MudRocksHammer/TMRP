#!/usr/bin/env bash

#set -e if check failed, exit immediately
#set -u if variable is not set, exit immediately
#set -o pipefail if any command in a pipeline fails, exit immediately
set -euo pipefail

# Change to the root of the repository
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."

echo "Running code quality checks, formatting checks, and tests..."
# インポート順序を自動修正する
.venv/bin/python -m ruff check --select I --fix src tests

# 改行や空白などを整形する
.venv/bin/python -m ruff format src tests

# 整形後にコード規約を確認する
.venv/bin/python -m ruff check src tests
echo "Code quality checks passed."

# 書式が整っていることを確認する
.venv/bin/python -m ruff format --check src tests
echo "Code formatting checks passed."

# run static type checks
.venv/bin/python -m mypy

# Run test
.venv/bin/python -m pytest -q