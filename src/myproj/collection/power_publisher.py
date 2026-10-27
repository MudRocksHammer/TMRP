import time
from threading import Event
from typing import Any

import paho.mqtt.client as mqtt
from loguru import logger
from paho.mqtt.enums import CallbackAPIVersion
from paho.mqtt.properties import Properties
from paho.mqtt.reasoncodes import ReasonCode

from myproj.app.receiver_config import ReceiverConfig
from myproj.telemetry.power import PowerTelemetry


class PublisherConfigurationError(RuntimeError):
    pass


class PowerPublisher:
    """一度に1件だけ送信確認を待つ。通信断時は同じ本文とイベントIDで再試行。"""

    def __init__(
        self, config: ReceiverConfig, *, client_id: str, password: str | None = None
    ) -> None:
        self.config, self.client_id, self.password = config, client_id, password
        self.client: mqtt.Client | None = None

    def _on_connect(
        self,
        client: mqtt.Client,
        userdata: Any,
        flags: mqtt.ConnectFlags,
        reason: ReasonCode,
        properties: Properties | None,
    ) -> None:
        if reason.is_failure:
            raise PublisherConfigurationError("Broker refused simulator connection")

    def _connect(self, stop: Event) -> bool:
        config = self.config
        client = mqtt.Client(
            callback_api_version=CallbackAPIVersion.VERSION2,
            client_id=self.client_id,
            clean_session=True,
            protocol=mqtt.MQTTv311,
            reconnect_on_failure=False,
        )
        self.client = client
        client.max_inflight_messages_set(1)
        client.max_queued_messages_set(1)
        client.connect_timeout = 5
        client.on_connect = self._on_connect
        if config.mqtt_username:
            client.username_pw_set(config.mqtt_username, self.password)
        if config.tls:
            try:
                client.tls_set(
                    ca_certs=config.ca_file or None,
                    certfile=config.cert_file or None,
                    keyfile=config.key_file or None,
                )
            except (OSError, ValueError) as exc:
                raise PublisherConfigurationError(
                    "Invalid simulator TLS config"
                ) from exc
        if client.connect(config.mqtt_host, config.mqtt_port, config.keepalive) != 0:
            raise ConnectionError("Connect failed")
        deadline = time.monotonic() + 10
        while not client.is_connected():
            if stop.is_set():
                return False
            if client.loop(timeout=0.2) != 0 or time.monotonic() >= deadline:
                raise ConnectionError("Connection acknowledgment timed out")
        return True

    def publish(self, message: PowerTelemetry, stop: Event) -> bool:
        payload = message.to_json()
        topic = f"tmrp/devices/{message.device_id}/telemetry"
        delay = 1
        while not stop.is_set():
            try:
                if self.client is None and not self._connect(stop):
                    return False
                assert self.client is not None
                info = self.client.publish(topic, payload, qos=1, retain=False)
                if info.rc != mqtt.MQTT_ERR_SUCCESS:
                    raise ConnectionError("Publish failed")
                deadline = time.monotonic() + 10
                while not info.is_published():
                    if stop.is_set():
                        return False
                    if (
                        self.client.loop(timeout=0.2) != 0
                        or time.monotonic() >= deadline
                    ):
                        raise ConnectionError("Publish acknowledgment timed out")
                return True
            except OSError:
                self.close()
                logger.bind(
                    device_id=message.device_id,
                    sequence_no=message.sequence_no,
                    retry_seconds=delay,
                ).warning("simulator_retrying_same_event")
                if stop.wait(delay):
                    return False
                delay = min(30, delay * 2)
        return False

    def wait_until(self, deadline: float, stop: Event) -> bool:
        while not stop.is_set():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return True
            timeout = min(0.2, remaining)
            if self.client is None:
                stop.wait(timeout)
            else:
                try:
                    if self.client.loop(timeout=timeout) != 0:
                        self.close()
                except OSError:
                    self.close()
        return False

    def close(self) -> None:
        if self.client is not None:
            self.client.disconnect()
            self.client = None
