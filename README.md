# TMRP
### Telemetry Monitoring and Replay Platform
**TMRP is an IoT telemetry platform for collecting, validating, storing, analyzing and replaying device telemetry data.**
**The project uses C++ for device simulation and Python for telemetry collection, validation, analytics, alarm processing and replay.**

## Project Status
### This project is under active development.
#### Current implementations:
- Telemetry message data model
- Runtime validation
- JSON serialization and deserialization
- JSON Lines telemetry reader
- Command-line interface
- JSON application configuration loading and validation
- Configurable JSON logging with Loguru for telemetry validation
- Sample telemetry analysis with NumPy, Pandas, and a reproducible Notebook
- Battery trend plots, time-based summaries, and UTC/Japan time zone comparison
- Unit tests
- Static type checking

#### Planned implementations:
- MQTT collector
- PostgreSQL storage
- Extended telemetry analytics
- Alarm processing
- Telemetry replay
- C++ device simulator
- Docker compose

## Requirements
- Python 3.12 or later
- Git
- Linux or WSL
### Future components may require:
- C++ 17 compiler
- CMake
- Mosquitto
- PostgreSQL
- Docker

## Setup
#### Clone repository
```bash
# TMRPリポジトリをローカル環境へ複製する
git clone https://github.com/MudRocksHammer/TMRP.git

# 複製したTMRPディレクトリへ移動する
cd TMRP
```
#### Create virtual environment
```bash
python3 --version

python3 -m venv .venv

source .venv/bin/activate
```
#### Install the project and development dependencies
```bash
python -m pip install -e ".[dev]"
```
#### Verify the installation
```bash
tmrp --version
```

#### Verify format, type checking, tests
```bash
bash scripts/check_test.sh
```

## Usage

Run these commands from the TMRP directory with the virtual environment activated.

#### Validate a telemetry JSON file:

```bash
# 正常なTelemetry JSONを検証する
tmrp validate examples/telemetry/valid.json
```

#### Check an application configuration file:

```bash
# 設定ファイルを検証し、実行環境とログレベルを表示する
tmrp check-config examples/config/valid.json
```

#### Validate telemetry with configured JSON logging:

```bash
# 設定のログレベルを適用してTelemetryを検証する
# 検証結果は標準出力、JSONログは標準エラーへ出る
tmrp validate examples/telemetry/valid.json --config examples/config/valid.json
```

`check-config` validates and displays settings. `validate --config` applies the
configured log level. Omitting `--config` preserves the plain-text CLI behavior.
See [configuration instructions](docs/configuration.md) for fields, defaults,
log format, expected output, and exit codes.

See [telemetry analysis instructions](docs/analysis.md) for analysis setup,
execution steps, plots, CSV reports, and expected results.

## Development checks

```bash
# 書式を自動修正し、lint・型チェック・テストを実行する
bash scripts/check_test.sh
```

Uses Ruff, mypy, and pytest.
See [verification instructions](docs/verification.md) for detailed checks.

## Testing Strategy
### The project uses the following test layers:
- Unit tests for telemetry validation
- Serialization and deserialization tests
- JSON Lines stream tests
- CLI tests
- Configuration validation and file-loading tests
- JSON log formatting, level filtering, and repeated logging setup tests
#### Future tests layers:
- MQTT integration tests
- PostgreSQL integration tests
- End-to-end telemetry pipeline tests
- Replay reproducibility tests
- Performance tests

## Design Principles
- C++ handles device-side and performance-sensitive processing
- Python handles collection, validation, analytics, testing and automation
- External input is validated before creating domain objects
- Internal timestamps are timezone-aware
- JSON timestamps are normalized to UTC
- Domain logic is separated from CLI and infrastructure code
- Tests, linting and type checking are treated as build gates
