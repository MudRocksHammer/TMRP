import shutil
import subprocess
from collections.abc import Iterator
from pathlib import Path

import pytest
from loguru import logger

from myproj.telemetry.models import TelemetryMessage


@pytest.fixture
def reset_loguru() -> Iterator[None]:
    """共有Loggerの出力先をテスト間に持ち越さない。"""
    logger.remove()
    try:
        yield
    finally:
        logger.remove()


@pytest.fixture
def sample_message() -> TelemetryMessage:
    project_root = Path(__file__).resolve().parents[1]
    text = (project_root / "examples/telemetry/valid.json").read_text(encoding="utf-8")
    return TelemetryMessage.from_json(text)


@pytest.fixture(scope="session")
def api_tls_material(tmp_path_factory):
    if not shutil.which("openssl"):
        pytest.skip("OpenSSL required for real HTTPS tests")
    folder = tmp_path_factory.mktemp("api-tls")
    cert, key = folder / "server.crt", folder / "server.key"
    subprocess.run(
        [
            "openssl",
            "req",
            "-x509",
            "-newkey",
            "rsa:2048",
            "-nodes",
            "-days",
            "1",
            "-keyout",
            str(key),
            "-out",
            str(cert),
            "-subj",
            "/CN=localhost",
            "-addext",
            "subjectAltName=DNS:localhost,IP:127.0.0.1",
        ],
        check=True,
        capture_output=True,
        timeout=15,
    )
    return cert, key
