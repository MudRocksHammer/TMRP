import argparse
import os
import signal
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from threading import Event
from types import FrameType
from uuid import uuid4

from loguru import logger

from myproj.app.receiver_config import load_receiver_config
from myproj.collection.power_publisher import (
    PowerPublisher,
    PublisherConfigurationError,
)
from myproj.collection.power_validation import load_power_devices
from myproj.telemetry.power_simulator import (
    PowerSimulator,
    next_deadline,
    validate_rate,
)

ROOT = Path(__file__).resolve().parents[2]


def main() -> int:
    parser = argparse.ArgumentParser(description="Continuous power telemetry simulator")
    parser.add_argument(
        "--config", type=Path, default=ROOT / "examples/power/simulator-local.toml"
    )
    rates = parser.add_mutually_exclusive_group()
    rates.add_argument(
        "--rate-hz", type=float, help="Messages per second per device (default: 1)"
    )
    rates.add_argument(
        "--total-rate", type=float, help="Total power messages per second"
    )
    parser.add_argument(
        "--cycles", type=int, default=0, help="Rounds per device; 0 runs until stopped"
    )
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    logger.remove()
    logger.add(sys.stderr, format="{time:HH:mm:ss} {level} {message} {extra}")
    try:
        config = load_receiver_config(args.config)
        devices = sorted(load_power_devices(Path(config.assets)))
        if args.cycles < 0:
            raise ValueError("cycles must be non-negative")
        rate = validate_rate(args.rate_hz if args.rate_hz is not None else 1.0)
        total_rate = (
            validate_rate(args.total_rate)
            if args.total_rate is not None
            else validate_rate(len(devices) * rate)
        )
        interval = 1.0 / total_rate
        simulator = PowerSimulator(devices, seed=args.seed)
    except (ValueError, OSError) as exc:
        logger.bind(error_type=type(exc).__name__).error(
            "simulator_configuration_invalid"
        )
        return 2

    stop = Event()

    def request_stop(signum: int, frame: FrameType | None) -> None:
        stop.set()

    previous = {
        sig: signal.signal(sig, request_stop) for sig in (signal.SIGINT, signal.SIGTERM)
    }
    publisher = PowerPublisher(
        config,
        client_id=f"sim-{uuid4().hex}",
        password=os.environ.get("TMRP_SIMULATOR_PASSWORD"),
    )
    confirmed = 0
    started = time.monotonic()
    deadline, last_report = started, started
    limit = args.cycles * len(devices)
    logger.bind(
        devices=len(devices),
        per_device_hz=total_rate / len(devices),
        target_messages_per_second=total_rate,
        boot_id=simulator.boot_id,
    ).info("simulator_started")
    try:
        while not stop.is_set() and (limit == 0 or confirmed < limit):
            if not publisher.wait_until(deadline, stop):
                break
            message = simulator.next_message(datetime.now(timezone.utc))
            if not publisher.publish(message, stop):
                break
            confirmed += 1
            now = time.monotonic()
            if now - last_report >= 10:
                logger.bind(
                    broker_confirmed=confirmed,
                    actual_messages_per_second=round(confirmed / (now - started), 2),
                ).info("simulator_progress")
                last_report = now
            deadline = next_deadline(deadline, now, interval)
        logger.bind(broker_confirmed=confirmed).info("simulator_stopped")
        return 0
    except (PublisherConfigurationError, ValueError):
        logger.error("simulator_connection_configuration_invalid")
        return 2
    except RuntimeError:
        logger.error("simulator_failed")
        return 1
    finally:
        publisher.close()
        for sig, handler in previous.items():
            signal.signal(sig, handler)


if __name__ == "__main__":
    raise SystemExit(main())
