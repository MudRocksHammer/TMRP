import hashlib
from datetime import datetime
from importlib.resources import files
from typing import Any, Literal

from psycopg import Connection
from psycopg.pq import TransactionStatus
from psycopg.types.json import Jsonb

from myproj.collection.power_validation import PowerReceipt

ReceiptOutcome = Literal["stored", "duplicate", "conflict", "rejected"]


def initialize_power_schema(conn: Connection[tuple[Any, ...]]) -> None:
    schema = files("myproj.persistence").joinpath("power_schema.sql").read_text()
    with conn.transaction():
        conn.execute(schema, prepare=False)


class PowerStore:
    def __init__(self, conn: Connection[tuple[Any, ...]]) -> None:
        if not conn.autocommit:
            raise ValueError(
                "PowerStore requires autocommit for transaction boundaries"
            )
        self.conn = conn
        # 未初期化DBで購読を始めない。
        conn.execute("SELECT device_id FROM power_telemetry LIMIT 0")
        conn.execute("SELECT reason FROM power_telemetry_rejections LIMIT 0")

    def probe(self) -> None:
        self.conn.execute("SELECT 1")

    def store(self, receipt: PowerReceipt) -> ReceiptOutcome:
        self._require_idle()
        message = receipt.message
        key = (message.device_id, message.boot_id, message.sequence_no)
        payload = message.to_dict()
        with self.conn.transaction():
            inserted = self.conn.execute(
                "INSERT INTO power_telemetry "
                "(device_id, boot_id, sequence_no, event_time, "
                "received_at, topic, payload) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s) "
                "ON CONFLICT (device_id, boot_id, sequence_no) DO NOTHING "
                "RETURNING sequence_no",
                (
                    *key,
                    message.event_time,
                    receipt.received_at,
                    receipt.topic,
                    Jsonb(payload),
                ),
            ).fetchone()
            if inserted is not None:
                outcome: ReceiptOutcome = "stored"
            else:
                existing = self.conn.execute(
                    "SELECT payload FROM power_telemetry "
                    "WHERE device_id=%s AND boot_id=%s AND sequence_no=%s",
                    key,
                ).fetchone()
                if existing is None:
                    raise RuntimeError("Conflicting event disappeared during receipt")
                if existing[0] == payload:
                    outcome = "duplicate"
                else:
                    self._reject(
                        receipt.topic,
                        message.to_json().encode("utf-8"),
                        "identity_conflict",
                        receipt.received_at,
                    )
                    outcome = "conflict"
        # transactionを抜けてCOMMITした後だけ結果を返す。
        return outcome

    def _reject(
        self, topic: str, payload: bytes, reason: str, received_at: datetime
    ) -> None:
        self.conn.execute(
            "INSERT INTO power_telemetry_rejections "
            "(received_at, topic, reason, payload_sha256, payload_bytes) "
            "VALUES (%s, %s, %s, %s, %s)",
            (
                received_at,
                topic.replace("\x00", "\\0")[:512],
                reason,
                hashlib.sha256(payload).hexdigest(),
                len(payload),
            ),
        )

    def reject(
        self, topic: str, payload: bytes, reason: str, received_at: datetime
    ) -> None:
        self._require_idle()
        with self.conn.transaction():
            self._reject(topic, payload, reason, received_at)

    def _require_idle(self) -> None:
        if self.conn.info.transaction_status != TransactionStatus.IDLE:
            raise ValueError("Receipt must not run inside an outer transaction")
