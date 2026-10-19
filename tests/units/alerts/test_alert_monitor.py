from datetime import datetime

import pytest

from myproj.alerts.battery import BatteryAlertKind, BatteryAlertMonitor
from myproj.telemetry.models import MessageType, TelemetryMessage


@pytest.fixture
def battery_percentages() -> tuple[list[float | None], list[BatteryAlertKind | None]]:
    return [30, 20, 19, 22, None, 25, 25, 20], [
        None,
        BatteryAlertKind.TRIGGERED,
        None,
        None,
        None,
        BatteryAlertKind.RECOVERED,
        None,
        BatteryAlertKind.TRIGGERED,
    ]


def test_battery_alert_monitor_continuous_input(
    battery_percentages: tuple[list[int], list[BatteryAlertKind | None]],
):
    battery_percentages, expected_results = battery_percentages
    monitor = BatteryAlertMonitor()
    device_id = "device_1"
    sequence_no = 1
    event_time = datetime.now().astimezone()

    # Simulate a series of battery percentages

    for battery_percent, expected in zip(battery_percentages, expected_results):
        message = TelemetryMessage(
            device_id=device_id,
            sequence_no=sequence_no,
            event_time=event_time,
            battery_percent=battery_percent,
            schema_version="1.0",
            message_type=MessageType.TELEMETRY,
        )
        event = monitor.process(message)
        sequence_no += 1
        assert (event.kind if event else None) == expected

        if expected is not None:
            assert event is not None
            assert event.device_id == message.device_id
            assert event.sequence_no == message.sequence_no
            assert event.event_time == message.event_time
            assert event.battery_percent == message.battery_percent


def test_battery_alert_monitor_start_low():
    monitor = BatteryAlertMonitor()
    device_id = "device_2"
    sequence_no = 1
    event_time = datetime.now().astimezone()

    # Simulate starting with a low battery percentage
    battery_percent = 20

    message = TelemetryMessage(
        device_id=device_id,
        sequence_no=sequence_no,
        event_time=event_time,
        battery_percent=battery_percent,
        schema_version="1.0",
        message_type=MessageType.TELEMETRY,
    )
    event = monitor.process(message)

    assert (event.kind if event else None) == BatteryAlertKind.TRIGGERED
    assert event is not None
    assert event.device_id == message.device_id
    assert event.sequence_no == message.sequence_no
    assert event.event_time == message.event_time
    assert event.battery_percent == message.battery_percent


def test_battery_alert_monitor_start_none_to_30():
    monitor = BatteryAlertMonitor()
    device_id = "device_3"
    sequence_no = 1
    event_time = datetime.now().astimezone()

    # Simulate starting with no battery percentage

    message = TelemetryMessage(
        device_id=device_id,
        sequence_no=sequence_no,
        event_time=event_time,
        battery_percent=None,
        schema_version="1.0",
        message_type=MessageType.TELEMETRY,
    )
    event = monitor.process(message)

    assert (event.kind if event else None) is None
    assert event is None

    message = TelemetryMessage(
        device_id=device_id,
        sequence_no=sequence_no + 1,
        event_time=event_time,
        battery_percent=30,
        schema_version="1.0",
        message_type=MessageType.TELEMETRY,
    )
    event = monitor.process(message)

    assert (event.kind if event else None) is None
    assert event is None


def test_battery_alert_monitor_device_independence(
    battery_percentages: tuple[list[int], list[BatteryAlertKind | None]],
):
    battery_percentages, expected_results = battery_percentages

    monitor = BatteryAlertMonitor()
    device_id_1 = "device_4"
    device_id_2 = "device_5"
    sequence_no = 1
    event_time = datetime.now().astimezone()

    for battery_percent, expected in zip(battery_percentages, expected_results):
        for device_id in (device_id_1, device_id_2):
            message = TelemetryMessage(
                device_id=device_id,
                sequence_no=sequence_no,
                event_time=event_time,
                battery_percent=battery_percent,
                schema_version="1.0",
                message_type=MessageType.TELEMETRY,
            )
            event = monitor.process(message)
            sequence_no += 1
            assert (event.kind if event else None) == expected

            if expected is not None:
                assert event is not None
                assert event.device_id == message.device_id
                assert event.sequence_no == message.sequence_no
                assert event.event_time == message.event_time
                assert event.battery_percent == message.battery_percent


def test_battery_alert_monitor_monitor_independence():
    monitor_1 = BatteryAlertMonitor()
    monitor_2 = BatteryAlertMonitor()

    device_id = "device_6"
    sequence_no = 1
    event_time = datetime.now().astimezone()

    message_1 = TelemetryMessage(
        device_id=device_id,
        sequence_no=sequence_no,
        event_time=event_time,
        battery_percent=20,
        schema_version="1.0",
        message_type=MessageType.TELEMETRY,
    )
    event_1 = monitor_1.process(message_1)
    event_2 = monitor_2.process(message_1)

    assert event_1 == event_2
    assert event_1.kind == BatteryAlertKind.TRIGGERED == event_2.kind
