"""Bounded WSS broadcast of committed telemetry and durable command results."""

import asyncio
from contextlib import suppress
from typing import Any

import psycopg
from fastapi import WebSocket
from fastapi.encoders import jsonable_encoder
from loguru import logger
from starlette.concurrency import run_in_threadpool

from myproj.app.receiver_health import ReceiverHealth
from myproj.persistence.control_store import ControlStore


class MonitorStream:
    def __init__(
        self,
        store: ControlStore,
        health: ReceiverHealth,
        devices: frozenset[str],
        equipment: dict[str, str],
    ) -> None:
        self.store, self.health = store, health
        self.devices, self.equipment = devices, equipment
        self.clients: dict[WebSocket, bool] = {}
        self.connections: set[WebSocket] = set()

    async def close(self, socket: WebSocket, code: int) -> None:
        self.clients.pop(socket, None)
        with suppress(OSError, RuntimeError, asyncio.TimeoutError):
            await asyncio.wait_for(socket.close(code=code), timeout=1)

    async def send(self, socket: WebSocket, data: dict[str, Any]) -> None:
        try:
            await asyncio.wait_for(
                socket.send_json(
                    {**data, "control_allowed": self.clients.get(socket, False)}
                ),
                timeout=1,
            )
        except (OSError, RuntimeError, asyncio.TimeoutError):
            await self.close(socket, 1013)

    async def run(self) -> None:
        try:
            while True:
                if self.clients:
                    try:
                        data = await run_in_threadpool(
                            self.store.monitor_snapshot, self.devices, self.equipment
                        )
                        data["mqtt_ready"] = bool(self.health.snapshot()["ready"])
                        for device in data["devices"]:
                            device["online"] &= data["mqtt_ready"]
                        encoded = jsonable_encoder(data)
                        await asyncio.gather(
                            *(self.send(ws, encoded) for ws in tuple(self.clients))
                        )
                    except psycopg.Error:
                        logger.warning("monitor_database_unavailable")
                        await asyncio.gather(
                            *(self.close(ws, 1013) for ws in tuple(self.clients))
                        )
                # Includes idle heartbeats; the client expires snapshots after 5s.
                await asyncio.sleep(1)
        finally:
            await asyncio.gather(*(self.close(ws, 1001) for ws in tuple(self.clients)))
