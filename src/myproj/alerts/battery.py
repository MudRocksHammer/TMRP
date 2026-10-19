from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from myproj.telemetry.models import TelemetryMessage


class BatteryAlertKind(Enum):
    TRIGGERED = "triggered"
    RECOVERED = "recovered"


class BatteryState(Enum):
    UNKNOWN = "unknown"
    NORMAL = "normal"
    LOW = "low"


@dataclass(frozen=True)
class BatteryAlertEvent:
    kind: BatteryAlertKind
    device_id: str
    sequence_no: int
    event_time: datetime
    battery_percent: float


class BatteryAlertMonitor:
    def __init__(self) -> None:
        self._states: dict[str, BatteryState] = {}

    def process(
        self,
        message: TelemetryMessage,
    ) -> BatteryAlertEvent | None:
        if message.battery_percent is None:
            return None
        current_state = self._states.get(message.device_id, BatteryState.UNKNOWN)
        next_state = next_battery_state(current_state, message.battery_percent)
        self._states[message.device_id] = next_state

        if current_state != next_state:
            if current_state == BatteryState.UNKNOWN and next_state == BatteryState.LOW:
                return BatteryAlertEvent(
                    kind=BatteryAlertKind.TRIGGERED,
                    device_id=message.device_id,
                    sequence_no=message.sequence_no,
                    event_time=message.event_time,
                    battery_percent=message.battery_percent,
                )
            elif (
                current_state == BatteryState.NORMAL and next_state == BatteryState.LOW
            ):
                return BatteryAlertEvent(
                    kind=BatteryAlertKind.TRIGGERED,
                    device_id=message.device_id,
                    sequence_no=message.sequence_no,
                    event_time=message.event_time,
                    battery_percent=message.battery_percent,
                )
            elif (
                current_state == BatteryState.LOW and next_state == BatteryState.NORMAL
            ):
                return BatteryAlertEvent(
                    kind=BatteryAlertKind.RECOVERED,
                    device_id=message.device_id,
                    sequence_no=message.sequence_no,
                    event_time=message.event_time,
                    battery_percent=message.battery_percent,
                )
        return None


def next_battery_state(
    current: BatteryState, battery_percent: float | None
) -> BatteryState:
    if battery_percent is None:
        return current
    if current == BatteryState.UNKNOWN:
        if battery_percent <= 20:
            return BatteryState.LOW
        return BatteryState.NORMAL
    elif current == BatteryState.NORMAL:
        if battery_percent <= 20:
            return BatteryState.LOW
        return BatteryState.NORMAL
    elif current == BatteryState.LOW:
        if battery_percent < 25:
            return BatteryState.LOW
        return BatteryState.NORMAL
    return BatteryState.UNKNOWN
