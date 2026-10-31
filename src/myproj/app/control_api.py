import asyncio
import base64
import os
import secrets
import ssl
import time
from datetime import timedelta
from threading import Thread
from typing import Annotated, Any

import psycopg
import uvicorn
from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from loguru import logger
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from myproj.app.receiver_config import ReceiverConfig
from myproj.app.receiver_health import ReceiverHealth
from myproj.collection.power_validation import strict_json
from myproj.persistence.control_store import CommandConflict, ControlStore
from myproj.telemetry.commands import CommandRequest


class HistoryCursor(BaseModel):
    model_config = ConfigDict(extra="forbid")
    event_time: AwareDatetime
    boot_id: str = Field(min_length=1, max_length=128, pattern=r"^[^\x00]+$")
    sequence_no: int = Field(strict=True, ge=0, le=2**63 - 1)


class RequestLimit:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["method"] != "POST":
            await self.app(scope, receive, send)
            return
        body = bytearray()
        try:
            async with asyncio.timeout(5):
                while True:
                    message = await receive()
                    if message["type"] == "http.disconnect":
                        return
                    body.extend(message.get("body", b""))
                    if len(body) > 16384:
                        await JSONResponse({"detail": "Request too large"}, 413)(
                            scope, receive, send
                        )
                        return
                    if not message.get("more_body", False):
                        break
        except TimeoutError:
            await JSONResponse({"detail": "Request timed out"}, 408)(
                scope, receive, send
            )
            return
        try:
            strict_json(body.decode("utf-8"))
        except (ValueError, UnicodeError):
            await JSONResponse({"detail": "Invalid JSON"}, 400)(scope, receive, send)
            return
        delivered = False

        async def buffered() -> Message:
            nonlocal delivered
            if not delivered:
                delivered = True
                return {"type": "http.request", "body": bytes(body), "more_body": False}
            return await receive()

        await self.app(scope, buffered, send)


def validate_api_settings(
    config: ReceiverConfig, devices: frozenset[str]
) -> tuple[str, str]:
    if config.api_command_targets.keys() - devices:
        raise ValueError("API command targets must be registered devices")
    read_token = os.environ.get("TMRP_API_READ_TOKEN", "")
    control_token = os.environ.get("TMRP_API_CONTROL_TOKEN", "")
    if (
        any(
            not 32 <= len(token) <= 256 or not token.isascii() or not token.isalnum()
            for token in (read_token, control_token)
        )
        or read_token == control_token
    ):
        raise ValueError(
            "Two distinct alphanumeric API tokens of 32..256 characters are required"
        )
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    # Do not prompt for a private-key password in unattended service startup.
    context.load_cert_chain(config.api_cert_file, config.api_key_file, password="")
    return read_token, control_token


def create_api(
    config: ReceiverConfig,
    store: ControlStore,
    health: ReceiverHealth,
    devices: frozenset[str],
    read_token: str,
    control_token: str,
) -> FastAPI:
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    app.add_middleware(RequestLimit)
    bearer = HTTPBearer(auto_error=False)

    def authorize(
        credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
    ) -> str:
        candidate = credentials.credentials.encode() if credentials else b""
        if secrets.compare_digest(candidate, control_token.encode()):
            return "control"
        if secrets.compare_digest(candidate, read_token.encode()):
            return "read"
        raise HTTPException(
            401, "Authentication required", headers={"WWW-Authenticate": "Bearer"}
        )

    def require_device(device_id: str) -> None:
        if device_id not in devices:
            raise HTTPException(404, "Unknown device")

    @app.exception_handler(psycopg.Error)
    async def database_error(request: Request, exc: psycopg.Error) -> JSONResponse:
        logger.bind(error_type=type(exc).__name__).error("api_database_unavailable")
        return JSONResponse({"detail": "Database unavailable"}, 503)

    @app.get("/health/ready", dependencies=[Depends(authorize)])
    def ready() -> JSONResponse:
        data = health.snapshot()
        return JSONResponse(data, 200 if data["ready"] else 503)

    @app.get("/api/v1/devices", dependencies=[Depends(authorize)])
    def list_devices() -> dict[str, Any]:
        return {
            "items": [
                {
                    "device_id": device,
                    "equipment_id": config.api_command_targets.get(device),
                    "controllable": device in config.api_command_targets,
                }
                for device in sorted(devices)
            ]
        }

    @app.get("/api/v1/devices/{device_id}/telemetry", dependencies=[Depends(authorize)])
    def history(
        device_id: str,
        start: AwareDatetime,
        end: AwareDatetime,
        limit: Annotated[int, Query(ge=1, le=1000)] = 100,
        cursor: Annotated[str | None, Query(max_length=1024)] = None,
    ) -> dict[str, Any]:
        require_device(device_id)
        if not timedelta(0) < end - start <= timedelta(days=31):
            raise HTTPException(422, "Use start < end with a range of at most 31 days")
        after = None
        if cursor:
            try:
                decoded = base64.b64decode(cursor, altchars=b"-_", validate=True)
                value = HistoryCursor.model_validate_json(decoded)
                after = (value.event_time, value.boot_id, value.sequence_no)
            except ValueError as exc:
                raise HTTPException(422, "Invalid cursor") from exc
        rows = store.history(device_id, start, end, limit, after)
        next_cursor = None
        if len(rows) > limit:
            last = rows[limit - 1]
            value = HistoryCursor(
                **{key: last[key] for key in HistoryCursor.model_fields}
            )
            next_cursor = base64.urlsafe_b64encode(
                value.model_dump_json().encode()
            ).decode()
        return {
            "items": [
                {"telemetry": row["payload"], "received_at": row["received_at"]}
                for row in rows[:limit]
            ],
            "next_cursor": next_cursor,
        }

    @app.post("/api/v1/devices/{device_id}/commands", status_code=202)
    def submit_command(
        device_id: str, body: CommandRequest, role: Annotated[str, Depends(authorize)]
    ) -> dict[str, Any]:
        if role != "control":
            raise HTTPException(403, "Control permission required")
        require_device(device_id)
        equipment = config.api_command_targets.get(device_id)
        if equipment is None:
            raise HTTPException(403, "Device is not enabled for control")
        try:
            result = store.create_command(device_id, equipment, body)
        except CommandConflict as exc:
            raise HTTPException(409, str(exc)) from exc
        logger.bind(
            device_id=device_id, command_id=body.command_id, operation=body.operation
        ).info("api_command_queued")
        return result

    @app.get(
        "/api/v1/devices/{device_id}/commands/{command_id}",
        dependencies=[Depends(authorize)],
    )
    def command_status(device_id: str, command_id: str) -> dict[str, Any]:
        require_device(device_id)
        if len(command_id) > 128:
            raise HTTPException(422, "Invalid command_id")
        result = store.get_command(device_id, command_id)
        if result is None:
            raise HTTPException(404, "Unknown command")
        return result

    return app


class APIServer:
    def __init__(self, config: ReceiverConfig, app: FastAPI) -> None:
        options = uvicorn.Config(
            app,
            host=config.api_host,
            port=config.api_port,
            ssl_certfile=config.api_cert_file,
            ssl_keyfile=config.api_key_file,
            ssl_keyfile_password="",
            ssl_version=ssl.PROTOCOL_TLS_SERVER,
            access_log=False,
            log_config=None,
            server_header=False,
            proxy_headers=False,
            limit_concurrency=32,
            timeout_keep_alive=5,
            timeout_graceful_shutdown=10,
            ws="none",
        )
        options.load()
        assert options.ssl is not None
        options.ssl.minimum_version = ssl.TLSVersion.TLSv1_2
        self.server = uvicorn.Server(options)
        self.thread = Thread(target=self.server.run, daemon=True, name="https-api")

    def start(self) -> None:
        self.thread.start()
        deadline = time.monotonic() + 10
        while not self.server.started:
            if not self.thread.is_alive() or time.monotonic() >= deadline:
                self.close()
                raise RuntimeError("HTTPS API failed to start")
            time.sleep(0.01)

    def close(self) -> None:
        self.server.should_exit = True
        if self.thread.ident is not None:
            self.thread.join(timeout=12)
