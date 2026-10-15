import asyncio

from myproj.async_pipeline import run_pipeline
from myproj.models import TelemetryMessage
from myproj.alerts import BatteryAlertEvent, BatteryAlertMonitor

def test_pipeline_empty_input() -> None:
    async def scenario() -> None:
        events = await asyncio.wait_for(
            run_pipeline({}, delay=0),
            timeout=1,
        )
        assert events == []

    asyncio.run(scenario())