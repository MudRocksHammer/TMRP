from myproj.models import TelemetryMessage, TelemetryValidationError


def parse_mqtt_telemetry(topic: str, payload: bytes) -> TelemetryMessage:
    parts = topic.split("/")
    if len(parts) != 4:
        raise TelemetryValidationError(f"トピックの形式が不正です: {topic}")
    if (
        parts[0] != "tmrp"
        or parts[1] != "devices"
        or not parts[2]
        or parts[3] != "telemetry"
    ):
        raise TelemetryValidationError(f"トピックの形式が不正です: {topic}")
    device_id = parts[2]
    telemetry_message = TelemetryMessage.from_json(payload.decode("utf-8"))
    if device_id != telemetry_message.device_id:
        raise TelemetryValidationError(
            f"device_idが一致しません: topicのdevice_id={device_id},"
            f"メッセージのdevice_id={telemetry_message.device_id}"
        )
    return telemetry_message
