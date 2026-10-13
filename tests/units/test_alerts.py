import pytest

from myproj.alerts import BatteryState, next_battery_state


@pytest.mark.parametrize(
    "battery_percent", [None, 0, 10, 20.0, 20.1, 24.9, 25.0, 50, 100]
)
def test_battery_percent(battery_percent: float | None) -> None:
    for current_state in BatteryState:
        next_state = next_battery_state(current_state, battery_percent)
        assert isinstance(next_state, BatteryState)

        if current_state == BatteryState.UNKNOWN:
            if battery_percent is None:
                assert next_state == BatteryState.UNKNOWN
            elif battery_percent <= 20:
                assert next_state == BatteryState.LOW
            else:
                assert next_state == BatteryState.NORMAL
        elif current_state == BatteryState.NORMAL:
            if battery_percent is None:
                assert next_state == BatteryState.NORMAL
            elif battery_percent <= 20:
                assert next_state == BatteryState.LOW
            else:
                assert next_state == BatteryState.NORMAL
        elif current_state == BatteryState.LOW:
            if battery_percent is None:
                assert next_state == BatteryState.LOW
            elif battery_percent < 25:
                assert next_state == BatteryState.LOW
            else:
                assert next_state == BatteryState.NORMAL


@pytest.mark.parametrize(
    ("current", "battery_percent", "expected"),
    [
        (BatteryState.NORMAL, None, BatteryState.NORMAL),
        (BatteryState.NORMAL, 20.0, BatteryState.LOW),
        (BatteryState.LOW, 24.9, BatteryState.LOW),
        (BatteryState.LOW, 25.0, BatteryState.NORMAL),
        # 課題の表に沿って残りを追加
    ],
)
def test_battery_state_transition(current, battery_percent, expected):
    assert next_battery_state(current, battery_percent) == expected


def test_battery_state_order() -> None:
    current_state = BatteryState.UNKNOWN
    battery_percent = 30
    current_state = next_battery_state(current_state, battery_percent)
    assert current_state == BatteryState.NORMAL

    battery_percent = 20
    current_state = next_battery_state(current_state, battery_percent)
    assert current_state == BatteryState.LOW

    battery_percent = 22
    current_state = next_battery_state(current_state, battery_percent)
    assert current_state == BatteryState.LOW

    battery_percent = None
    current_state = next_battery_state(current_state, battery_percent)
    assert current_state == BatteryState.LOW

    battery_percent = 24.9
    current_state = next_battery_state(current_state, battery_percent)
    assert current_state == BatteryState.LOW

    battery_percent = 25
    current_state = next_battery_state(current_state, battery_percent)
    assert current_state == BatteryState.NORMAL

    battery_percent = 20
    current_state = next_battery_state(current_state, battery_percent)
    assert current_state == BatteryState.LOW
