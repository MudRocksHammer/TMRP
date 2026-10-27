from collections.abc import Callable
from datetime import datetime, timezone
from time import perf_counter
from typing import Protocol
from uuid import uuid4

from loguru import logger

from myproj.collection.power_validation import (
    PowerReceipt,
    PowerValidator,
    RejectedTelemetry,
)
from myproj.persistence.power_storage import ReceiptOutcome


class ReceiptStore(Protocol):
    def store(self, receipt: PowerReceipt) -> ReceiptOutcome: ...

    def reject(
        self, topic: str, payload: bytes, reason: str, received_at: datetime
    ) -> None: ...


class PowerReceiver:
    def __init__(
        self,
        validator: PowerValidator,
        store: ReceiptStore,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.validator = validator
        self.store = store
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    def handle(
        self,
        topic: str,
        payload: bytes,
        *,
        qos: int,
        retain: bool,
        acknowledge: Callable[[], None],
    ) -> ReceiptOutcome:
        started = perf_counter()
        received_at = self.clock()
        log = logger.bind(
            receipt_id=uuid4().hex,
            topic=topic[:512],
            payload_bytes=len(payload),
            qos=qos,
            retain=retain,
            received_at=received_at.isoformat(),
        )
        log.info("telemetry_received")
        stage = "validation"
        outcome: ReceiptOutcome | None = None
        try:
            try:
                receipt = self.validator.parse(
                    topic, payload, received_at=received_at, qos=qos, retain=retain
                )
            except RejectedTelemetry as exc:
                log = log.bind(reason=exc.code)
                stage = "persist_rejection"
                self.store.reject(topic, payload, exc.code, received_at)
                outcome = "rejected"
            else:
                log = log.bind(
                    device_id=receipt.message.device_id,
                    boot_id=receipt.message.boot_id,
                    sequence_no=receipt.message.sequence_no,
                    event_time=receipt.message.event_time.isoformat(),
                )
                stage = "persist_telemetry"
                outcome = self.store.store(receipt)
                if outcome == "conflict":
                    log = log.bind(reason="identity_conflict")
            stage = "acknowledge"
            if qos >= 1:
                acknowledge()
        except Exception as exc:
            # 例外本文・tracebackには資格情報や入力が含まれ得るため型だけ記録する。
            log.bind(
                stage=stage,
                outcome=outcome,
                persistence_completed=outcome is not None,
                error_type=type(exc).__name__,
                elapsed_ms=round((perf_counter() - started) * 1000, 3),
            ).error("telemetry_processing_failed")
            raise

        result_log = log.bind(
            outcome=outcome,
            ack_requested=qos >= 1,
            elapsed_ms=round((perf_counter() - started) * 1000, 3),
        )
        if outcome in {"rejected", "conflict"}:
            result_log.warning("telemetry_rejected")
        else:
            result_log.info("telemetry_processed")
        return outcome
