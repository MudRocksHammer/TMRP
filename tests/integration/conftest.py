import os
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import psycopg
import pytest
from psycopg import Connection

from myproj.models import TelemetryMessage

PROJECT_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def db_conn() -> Iterator[Connection[tuple[Any, ...]]]:
    dsn = os.environ.get("TMRP_TEST_DSN")
    if not dsn:
        pytest.skip("TMRP_TEST_DSN environment variable is not set")

    schema = (PROJECT_ROOT / "sql/001_create_telemetry.sql").read_text(encoding="utf-8")

    schema = schema.replace(
        "CREATE TABLE telemetry_messages", "CREATE TEMP TABLE telemetry_messages", 1
    )

    with psycopg.connect(
        dsn,
        autocommit=True,
        options="-c timezone=UTC -c search_path=pg_temp",
    ) as conn:
        conn.execute(schema)
        yield conn


@pytest.fixture
def sample_message() -> TelemetryMessage:
    text = (PROJECT_ROOT / "examples/telemetry/valid.json").read_text(encoding="utf-8")
    return TelemetryMessage.from_json(text)


@pytest.fixture
def sample_dsn() -> str:
    dsn = os.environ.get("TMRP_TEST_DSN")
    if not dsn:
        pytest.skip("TMRP_TEST_DSN environment variable is not set")
    return dsn


@pytest.fixture
def sample_schema() -> str:
    project_root = Path(__file__).resolve().parents[2]
    schema = (project_root / "sql/001_create_telemetry.sql").read_text(encoding="utf-8")
    schema = schema.replace(
        "CREATE TABLE telemetry_messages",
        "CREATE TEMP TABLE telemetry_messages",
        1,
    )
    return schema
