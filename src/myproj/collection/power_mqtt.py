import json
import time
from threading import Event
from typing import Any

import paho.mqtt.client as mqtt
from loguru import logger
from paho.mqtt.enums import CallbackAPIVersion
from paho.mqtt.properties import Properties
from paho.mqtt.reasoncodes import ReasonCode

from myproj.app.receiver_config import ReceiverConfig
from myproj.app.receiver_health import ReceiverHealth
from myproj.collection.power_receiver import PowerReceiver
from myproj.collection.power_validation import strict_json
from myproj.persistence.control_store import CommandOutbox
from myproj.persistence.power_storage import PowerStore
from myproj.telemetry.commands import CommandResult


class MQTTConfigurationError(RuntimeError):
    pass


class ReceiptFailure(RuntimeError):
    pass


class PowerMQTTService:
    def __init__(
        self,
        config: ReceiverConfig,
        receiver: PowerReceiver,
        store: PowerStore,
        health: ReceiverHealth,
        *,
        password: str | None = None,
        commands: CommandOutbox | None = None,
    ) -> None:
        self.config, self.receiver, self.store, self.health = (
            config,
            receiver,
            store,
            health,
        )
        self._delay = 1
        self.commands = commands
        self._subscribed = False
        self._next_dispatch = 0.0
        self.client = mqtt.Client(
            callback_api_version=CallbackAPIVersion.VERSION2,
            client_id=config.client_id,
            clean_session=False,
            protocol=mqtt.MQTTv311,
            manual_ack=True,
            reconnect_on_failure=False,
        )
        self.client.connect_timeout = 5
        self.client.max_queued_messages_set(32)
        if config.mqtt_username:
            self.client.username_pw_set(config.mqtt_username, password)
        if config.tls:
            self.client.tls_set(
                ca_certs=config.ca_file or None,
                certfile=config.cert_file or None,
                keyfile=config.key_file or None,
            )
        self.client.on_connect = self._on_connect
        self.client.on_subscribe = self._on_subscribe
        self.client.on_message = self._on_message

    def _on_connect(
        self,
        client: mqtt.Client,
        userdata: Any,
        flags: mqtt.ConnectFlags,
        reason: ReasonCode,
        properties: Properties | None,
    ) -> None:
        if reason.is_failure:
            raise MQTTConfigurationError("Broker refused connection")
        topics = [("tmrp/devices/+/telemetry", 1)]
        if self.commands is not None:
            topics.append(("tmrp/devices/+/command-results", 1))
        result, _ = client.subscribe(topics)
        if result != mqtt.MQTT_ERR_SUCCESS:
            raise ConnectionError("Subscribe request failed")

    def _on_subscribe(
        self,
        client: mqtt.Client,
        userdata: Any,
        mid: int,
        reasons: list[ReasonCode],
        properties: Properties | None,
    ) -> None:
        if not reasons or any(reason.value != 1 for reason in reasons):
            raise MQTTConfigurationError("Broker must grant QoS 1")
        self.store.probe()
        self._delay = 1
        self._subscribed = True
        self.health.touch(ready=True)
        logger.info("mqtt_subscription_ready")

    def _on_message(
        self, client: mqtt.Client, userdata: Any, message: mqtt.MQTTMessage
    ) -> None:
        def acknowledge() -> None:
            if client.ack(message.mid, message.qos) != mqtt.MQTT_ERR_SUCCESS:
                raise ConnectionError("Acknowledgment failed")

        try:
            if self.commands is not None and message.topic.endswith("/command-results"):
                outcome = "command_result"
                try:
                    if (
                        message.retain
                        or message.qos != 1
                        or len(message.payload) > 16384
                    ):
                        raise ValueError("Invalid command result envelope")
                    result = CommandResult.model_validate(
                        strict_json(bytes(message.payload).decode("utf-8"))
                    )
                    if (
                        message.topic
                        != f"tmrp/devices/{result.device_id}/command-results"
                    ):
                        raise ValueError("Topic mismatch")
                except (ValueError, UnicodeError):
                    logger.warning("command_result_rejected")
                else:
                    self.commands.save_result(result)
                    logger.bind(
                        device_id=result.device_id,
                        command_id=result.command_id,
                        status=result.status,
                    ).info("command_result_received")
                acknowledge()
            else:
                outcome = self.receiver.handle(
                    message.topic,
                    bytes(message.payload),
                    qos=message.qos,
                    retain=message.retain,
                    acknowledge=acknowledge,
                )
        except Exception as exc:
            # DBの失敗を通信エラーとして再試行しない。未ACKのまま失敗終了。
            self.health.touch(ready=False)
            raise ReceiptFailure("Receipt failed") from exc
        self.health.touch(outcome=outcome)

    def _dispatch_commands(self) -> None:
        if (
            self.commands is None
            or not self._subscribed
            or time.monotonic() < self._next_dispatch
        ):
            return
        self._next_dispatch = time.monotonic() + 1
        for command in self.commands.due():
            info = self.client.publish(
                f"tmrp/devices/{command['device_id']}/commands",
                json.dumps(command),
                qos=1,
                retain=False,
            )
            if info.rc != mqtt.MQTT_ERR_SUCCESS:
                raise ConnectionError("Command publish unavailable")

    def run(self, stop: Event) -> None:
        try:
            while not stop.is_set():
                self._subscribed = False
                self.health.touch(ready=False)
                try:
                    result = self.client.connect(
                        self.config.mqtt_host,
                        self.config.mqtt_port,
                        self.config.keepalive,
                    )
                    if result != mqtt.MQTT_ERR_SUCCESS:
                        raise ConnectionError("Connect failed")
                    next_probe = time.monotonic() + 5
                    while not stop.is_set():
                        if self.client.loop(timeout=1) != mqtt.MQTT_ERR_SUCCESS:
                            raise ConnectionError("Connection lost")
                        self._dispatch_commands()
                        if time.monotonic() >= next_probe:
                            self.store.probe()
                            next_probe = time.monotonic() + 5
                        self.health.touch()
                except OSError:
                    logger.bind(delay_seconds=self._delay).warning("mqtt_reconnecting")
                finally:
                    self.health.touch(ready=False)
                    self.client.disconnect()
                # 再接続待機中もlivenessを更新し、SIGTERMへ応答する。
                for _ in range(self._delay):
                    if stop.wait(1):
                        break
                    self.health.touch(ready=False)
                self._delay = min(30, self._delay * 2)
        finally:
            self.health.touch(ready=False)
            self.client.disconnect()
