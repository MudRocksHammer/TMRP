import argparse
import os
import signal
import sys
from pathlib import Path
from threading import Event
from types import FrameType

import psycopg
from loguru import logger

from myproj.app.control_api import APIServer, create_api, validate_api_settings
from myproj.app.receiver_config import load_receiver_config
from myproj.app.receiver_health import HealthServer, ReceiverHealth
from myproj.collection.power_mqtt import MQTTConfigurationError, PowerMQTTService
from myproj.collection.power_receiver import PowerReceiver
from myproj.collection.power_validation import PowerValidator, load_power_devices
from myproj.persistence.control_store import CommandOutbox, ControlStore
from myproj.persistence.power_storage import PowerStore, initialize_power_schema


def main() -> int:
    parser = argparse.ArgumentParser(description="TMRP power telemetry receiver server")
    parser.add_argument("--config", type=Path, required=True)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--init-db", action="store_true", help="Initialize power tables and exit"
    )
    mode.add_argument(
        "--check-config",
        action="store_true",
        help="Validate config and assets without network access",
    )
    args = parser.parse_args()
    logger.remove()
    logger.add(sys.stderr, serialize=True, backtrace=False, diagnose=False)
    try:
        config = load_receiver_config(args.config)
        validator = PowerValidator(
            load_power_devices(Path(config.assets)), config.max_payload_bytes
        )
        api_tokens = (
            validate_api_settings(config, validator.device_ids)
            if config.api_enabled
            else None
        )
        if args.check_config:
            logger.info("receiver_config_valid")
            return 0
        dsn = os.environ.get("TMRP_RECEIVER_DSN")
        if not dsn:
            raise ValueError("TMRP_RECEIVER_DSN is required")
    except (OSError, ValueError):
        # DSNや資格情報を例外文字列・ローカル変数としてログへ流さない。
        logger.error("receiver_configuration_invalid")
        return 2

    stop = Event()
    health_server: HealthServer | None = None
    api_server: APIServer | None = None

    def request_stop(signum: int, frame: FrameType | None) -> None:
        stop.set()

    previous = {
        sig: signal.signal(sig, request_stop) for sig in (signal.SIGINT, signal.SIGTERM)
    }
    try:
        with psycopg.connect(
            dsn,
            autocommit=True,
            connect_timeout=5,
            keepalives=1,
            keepalives_idle=10,
            keepalives_interval=5,
            keepalives_count=2,
            tcp_user_timeout=10000,
        ) as conn:
            conn.execute("SET statement_timeout = '5s'")
            conn.execute("SET lock_timeout = '3s'")
            conn.execute("SET synchronous_commit = on")
            conn.execute("SET timezone = 'UTC'")
            if args.init_db:
                initialize_power_schema(conn)
                logger.info("power_schema_initialized")
                return 0
            store = PowerStore(conn)
            health = ReceiverHealth()
            health_server = HealthServer(config.health_host, config.health_port, health)
            health_server.start()
            commands = CommandOutbox(conn) if config.api_enabled else None
            if api_tokens is not None:
                api_server = APIServer(
                    config,
                    create_api(
                        config,
                        ControlStore(dsn),
                        health,
                        validator.device_ids,
                        *api_tokens,
                    ),
                )
                api_server.start()
                logger.bind(host=config.api_host, port=config.api_port).info(
                    "https_api_started"
                )
            try:
                service = PowerMQTTService(
                    config,
                    PowerReceiver(validator, store),
                    store,
                    health,
                    password=os.environ.get("TMRP_MQTT_PASSWORD"),
                    commands=commands,
                )
            except (OSError, ValueError) as exc:
                raise MQTTConfigurationError("Invalid MQTT/TLS configuration") from exc
            service.run(stop)
            logger.bind(status=health.snapshot()).info("receiver_stopped")
            return 0
    except MQTTConfigurationError:
        logger.error("mqtt_configuration_rejected")
        return 2
    except (OSError, ValueError, RuntimeError, psycopg.Error) as exc:
        logger.bind(error_type=type(exc).__name__).error("receiver_failed")
        return 1
    finally:
        if api_server is not None:
            api_server.close()
        if health_server is not None:
            health_server.close()
        for sig, handler in previous.items():
            signal.signal(sig, handler)


if __name__ == "__main__":
    raise SystemExit(main())
