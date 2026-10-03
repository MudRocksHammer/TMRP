import argparse
import sys
from importlib.metadata import version
from pathlib import Path

from myproj.config import ConfigLoadError, ConfigValidationError, load_config
from myproj.logging_config import configure_logging
from myproj.models import TelemetryMessage, TelemetryValidationError


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="tmrp")
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {'version:' + version('TMRP')}",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)
    validate_parser = subparsers.add_parser("validate")
    validate_parser.add_argument("path", type=Path)
    check_config_parser = subparsers.add_parser(
        "check-config",
    )
    check_config_parser.add_argument("path", type=Path)

    validate_parser.add_argument("--config", type=Path)

    args = parser.parse_args(argv)

    if args.command == "validate":
        logger = None
        if args.config:
            try:
                config = load_config(args.config)
                logger = configure_logging(config)
            except (ConfigValidationError, ConfigLoadError) as e:
                print(f"Error: {e}", file=sys.stderr)
                return 1
        try:
            try:
                text = args.path.read_text(encoding="utf-8")
                message = TelemetryMessage.from_json(text)
            except (OSError, UnicodeError, TelemetryValidationError) as e:
                if logger is not None:
                    logger.error("Error: {}", e)
                else:
                    print(f"Error: {e}", file=sys.stderr)
                return 1

            print(
                f"device_id={message.device_id} "
                f"sequence_no={message.sequence_no} "
                f"event_time={message.event_time.isoformat()}"
            )
            if logger is not None:
                logger.info(
                    "device_id={} sequence_no={} event_time={}",
                    message.device_id,
                    message.sequence_no,
                    message.event_time.isoformat(),
                )
            return 0
        finally:
            if logger is not None:
                logger.complete()
    elif args.command == "check-config":
        try:
            config = load_config(args.path)
        except (ConfigValidationError, ConfigLoadError) as e:
            print(f"Error: {e}", file=sys.stderr)
            return 1
        print(f"environment={config.environment} log_level={config.log_level}")
        return 0

    print(f"Error: Unknown command {args.command}", file=sys.stderr)

    return 2


if __name__ == "__main__":
    raise SystemExit(main())
