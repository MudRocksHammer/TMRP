import argparse
import sys
from importlib.metadata import version
from pathlib import Path

from myproj.models import TelemetryMessage, TelemetryValidationError


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="iot-telemetry")
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {'version:' + version('TMRP')}",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)
    validate_parser = subparsers.add_parser("validate")
    validate_parser.add_argument("path", type=Path)

    args = parser.parse_args(argv)

    if args.command == "validate":
        try:
            text = args.path.read_text(encoding="utf-8")
            message = TelemetryMessage.from_json(text)
        except (OSError, UnicodeError, TelemetryValidationError) as e:
            print(f"Error: {e}", file=sys.stderr)
            return 1

        print(
            f"device_id={message.device_id} "
            f"sequence_no={message.sequence_no} "
            f"event_time={message.event_time.isoformat()}"
        )
        return 0

    print(f"Error: Unknown command {args.command}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
