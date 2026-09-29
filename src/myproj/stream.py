from collections.abc import Iterable, Iterator

from myproj.models import TelemetryMessage, TelemetryValidationError


def iter_telemetry(lines: Iterable[str]) -> Iterator[TelemetryMessage]:
    for i, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            yield TelemetryMessage.from_json(line)
        except TelemetryValidationError as e:
            raise TelemetryValidationError(f"Error in line {i}: {e}") from e
