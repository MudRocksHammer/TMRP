import math
import random
from datetime import datetime
from uuid import uuid4

from myproj.collection.power_validation import topic_device_id
from myproj.telemetry.messageType import MessageType
from myproj.telemetry.power import BreakerState, MeasurementQuality, PowerTelemetry


def validate_rate(rate_hz: float) -> float:
    if isinstance(rate_hz, bool) or not isinstance(rate_hz, (int, float)):
        raise ValueError("rate_hz must be a finite positive number")
    if not math.isfinite(rate_hz) or rate_hz <= 0:
        raise ValueError("rate_hz must be a finite positive number")
    return float(rate_hz)


def next_deadline(previous: float, now: float, interval: float) -> float:
    planned = previous + interval
    # 遅れを大量の追い付き送信で解消しない。停止中の観測は生成しない。
    return planned if planned >= now else now + interval


class PowerSimulator:
    def __init__(
        self, device_ids: list[str], *, seed: int = 42, boot_id: str | None = None
    ) -> None:
        if not device_ids or len(set(device_ids)) != len(device_ids):
            raise ValueError("Non-empty unique device IDs are required")
        for device_id in device_ids:
            topic_device_id(f"tmrp/devices/{device_id}/telemetry")
        self.device_ids = tuple(device_ids)
        self.boot_id = boot_id if boot_id is not None else str(uuid4())
        if (
            not self.boot_id
            or self.boot_id != self.boot_id.strip()
            or len(self.boot_id) > 128
        ):
            raise ValueError("Invalid boot_id")
        self._rng = random.Random(seed)
        self._index = 0

    def next_message(self, event_time: datetime) -> PowerTelemetry:
        sequence, device_index = divmod(self._index, len(self.device_ids))
        # デモ用の緩やかな負荷変化。設備の物理モデルや運転閾値ではない。
        load = 1 + 0.15 * math.sin(sequence / 30 + device_index / 3)
        load += self._rng.uniform(-0.02, 0.02)
        message = PowerTelemetry(
            schema_version="1.0",
            message_type=MessageType.POWER,
            device_id=self.device_ids[device_index],
            boot_id=self.boot_id,
            sequence_no=sequence,
            event_time=event_time,
            breaker_state=BreakerState.CLOSED,
            quality=MeasurementQuality.GOOD,
            voltage_ab_v=10000.0,
            voltage_bc_v=9990.0,
            voltage_ca_v=10010.0,
            current_a_a=100 * load,
            current_b_a=101 * load,
            current_c_a=99 * load,
            active_power_kw=1500 * load,
            frequency_hz=50.0,
        )
        self._index += 1
        return message
