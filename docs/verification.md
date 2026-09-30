#### Verify format, type checking, and tests

Run the following command from the TMRP directory:

```bash
# インポート順序と書式を自動修正し、lint・型チェック・テストを実行する
bash scripts/check_test.sh
```

This script automatically fixes import ordering and formatting.
It then runs Ruff checks, strict mypy checks on `src`, and pytest.

Expected results for Week 1:

- Ruff lint and formatting checks pass.
- mypy reports no issues in 4 source files.
- All 117 tests pass.

## Usage

The following commands assume that the virtual environment is activated
and the current directory is TMRP.

### Show the version

```bash
# インストールしたCLIのバージョンを表示する
tmrp --version
```

### Validate a valid JSON file

```bash
# 正常な遥測JSONを検証する
tmrp validate examples/telemetry/valid.json

# 直前の終了コードを表示する。期待値は0
echo $?
```

Expected output:

```text
device_id=robot-001 sequence_no=1001 event_time=2024-06-01T12:00:00+00:00
```

### Validate an invalid JSON file

```bash
# device_idが欠けた遥測JSONを検証する
tmrp validate examples/telemetry/invalid/missing-device-id.json

# 直前の終了コードを表示する。期待値は1
echo $?
```

An error mentioning `device_id` is written to standard error.

### Exit codes

| Code | Meaning                                    |
| ---- | ------------------------------------------ |
| 0    | Success                                    |
| 1    | File reading or telemetry validation error |
| 2    | Invalid command-line arguments             |

The `validate` command accepts one JSON object per file.
JSON Lines reading is currently available through the Python API.