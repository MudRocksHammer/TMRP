from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import Any

import psycopg
from psycopg import Connection
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from myproj.telemetry.commands import CommandRequest, CommandResult


class CommandConflict(ValueError):
    pass


class ControlStore:
    """API requests use separate connections; never share the receiver connection."""

    def __init__(self, dsn: str) -> None:
        self.dsn = dsn

    @contextmanager
    def connection(self) -> Iterator[Connection[dict[str, Any]]]:
        with psycopg.connect(
            self.dsn, autocommit=True, connect_timeout=5, row_factory=dict_row
        ) as conn:
            conn.execute("SET statement_timeout = '5s'")
            conn.execute("SET lock_timeout = '2s'")
            conn.execute("SET synchronous_commit = on")
            conn.execute("SET timezone = 'UTC'")
            yield conn

    def history(
        self,
        device_id: str,
        start: datetime,
        end: datetime,
        limit: int,
        after: tuple[datetime, str, int] | None = None,
    ) -> list[dict[str, Any]]:
        query = (
            "SELECT event_time, boot_id, sequence_no, received_at, payload "
            "FROM power_telemetry WHERE device_id=%s "
            "AND event_time >= %s AND event_time < %s "
        )
        values: list[Any] = [device_id, start, end]
        if after is not None:
            query += "AND (event_time, boot_id, sequence_no) > (%s, %s, %s) "
            values.extend(after)
        query += "ORDER BY event_time, boot_id, sequence_no LIMIT %s"
        values.append(limit + 1)
        with self.connection() as conn:
            return list(conn.execute(query, values).fetchall())

    def create_command(
        self, device_id: str, equipment_id: str, request: CommandRequest
    ) -> dict[str, Any]:
        now = datetime.now(timezone.utc)
        expires = now + timedelta(seconds=request.expires_in_seconds)
        body = request.model_dump()
        payload: dict[str, Any] = {
            "schema_version": "1.0",
            "message_type": "command",
            "command_id": request.command_id,
            "device_id": device_id,
            "equipment_id": equipment_id,
            "operation": request.operation,
            "issued_at": now.isoformat(),
            "expires_at": expires.isoformat(),
        }
        if request.expected_state_version is not None:
            payload["expected_state_version"] = request.expected_state_version
        with self.connection() as conn, conn.transaction():
            conn.execute(
                "INSERT INTO device_commands "
                "(device_id, command_id, request, payload, expires_at) "
                "VALUES (%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                (device_id, request.command_id, Jsonb(body), Jsonb(payload), expires),
            )
            row = conn.execute(
                "SELECT * FROM device_commands WHERE device_id=%s AND command_id=%s",
                (device_id, request.command_id),
            ).fetchone()
            assert row is not None
            if row["request"] != body or row["payload"]["equipment_id"] != equipment_id:
                raise CommandConflict("command_id was already used for another request")
            return command_view(row)

    def get_command(self, device_id: str, command_id: str) -> dict[str, Any] | None:
        with self.connection() as conn:
            row = conn.execute(
                "SELECT * FROM device_commands WHERE device_id=%s AND command_id=%s",
                (device_id, command_id),
            ).fetchone()
        return command_view(row) if row else None


def command_view(row: dict[str, Any]) -> dict[str, Any]:
    result = row["result"]
    # Expiry without a final result does not prove whether the equipment operated.
    if result and result["status"] != "accepted":
        status = result["status"]
    elif row["expires_at"] <= datetime.now(timezone.utc):
        status = "unknown"
    elif result:
        status = "accepted"
    else:
        status = "queued" if row["publish_attempts"] == 0 else "awaiting_result"
    return {
        "command": row["payload"],
        "status": status,
        "publish_attempts": row["publish_attempts"],
        "result": result,
        "result_received_at": row["result_received_at"],
    }


class CommandOutbox:
    """Used only by the MQTT loop, with its own existing autocommit connection."""

    def __init__(self, conn: Connection[tuple[Any, ...]]) -> None:
        self.conn = conn
        conn.execute("SELECT command_id FROM device_commands LIMIT 0")

    def due(self) -> list[dict[str, Any]]:
        # Schedule before publishing; a crash delays retry but does not lose it.
        with self.conn.transaction():
            rows = self.conn.execute(
                "WITH due AS (SELECT device_id, command_id FROM device_commands "
                "WHERE expires_at > now() AND next_attempt_at <= now() "
                "AND (result IS NULL OR result->>'status'='accepted') "
                "ORDER BY next_attempt_at LIMIT 16 FOR UPDATE SKIP LOCKED) "
                "UPDATE device_commands c "
                "SET next_attempt_at=now()+interval '5 seconds', "
                "publish_attempts=publish_attempts+1 FROM due "
                "WHERE c.device_id=due.device_id AND c.command_id=due.command_id "
                "RETURNING c.payload"
            ).fetchall()
        return [row[0] for row in rows]

    def save_result(self, result: CommandResult) -> bool:
        with self.conn.transaction():
            row = self.conn.execute(
                "UPDATE device_commands SET result=%s, result_received_at=now() "
                "WHERE device_id=%s AND command_id=%s AND payload->>'equipment_id'=%s "
                "AND (result IS NULL OR result->>'status'='accepted') "
                "RETURNING command_id",
                (
                    Jsonb(result.model_dump(mode="json")),
                    result.device_id,
                    result.command_id,
                    result.equipment_id,
                ),
            ).fetchone()
        return row is not None
