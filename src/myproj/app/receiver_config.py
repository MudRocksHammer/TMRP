import tomllib
from dataclasses import dataclass, fields
from pathlib import Path


@dataclass(frozen=True)
class ReceiverConfig:
    assets: str
    client_id: str
    mqtt_host: str = "127.0.0.1"
    mqtt_port: int = 18884
    keepalive: int = 30
    mqtt_username: str = ""
    tls: bool = False
    ca_file: str = ""
    cert_file: str = ""
    key_file: str = ""
    health_host: str = "127.0.0.1"
    health_port: int = 8081
    max_payload_bytes: int = 16384

    def __post_init__(self) -> None:
        for name in ("assets", "client_id", "mqtt_host", "health_host"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value or value != value.strip():
                raise ValueError(f"Invalid {name}")
        for name in ("mqtt_username", "ca_file", "cert_file", "key_file"):
            if not isinstance(getattr(self, name), str):
                raise ValueError(f"Invalid {name}")
        if not isinstance(self.tls, bool):
            raise ValueError("tls must be a boolean")
        for name in ("mqtt_port", "health_port", "keepalive", "max_payload_bytes"):
            value = getattr(self, name)
            upper = 1048576 if name == "max_payload_bytes" else 65535
            if (
                isinstance(value, bool)
                or not isinstance(value, int)
                or not 1 <= value <= upper
            ):
                raise ValueError(f"Invalid {name}")
        if bool(self.cert_file) != bool(self.key_file):
            raise ValueError("cert_file and key_file must be provided together")
        if (self.ca_file or self.cert_file) and not self.tls:
            raise ValueError("Certificate configuration requires tls=true")
        if self.mqtt_host not in {"127.0.0.1", "localhost", "::1"} and not self.tls:
            raise ValueError("Remote MQTT connections require TLS")


def load_receiver_config(path: Path) -> ReceiverConfig:
    with path.open("rb") as source:
        values = tomllib.load(source)
    if values.keys() - {field.name for field in fields(ReceiverConfig)}:
        raise ValueError("Unknown receiver configuration keys")
    if not {"assets", "client_id"} <= values.keys():
        raise ValueError("assets and client_id are required")
    config = ReceiverConfig(**values)
    # パスは設定ファイルの位置を基準に解決し、systemdのcwdに依存させない。
    for name in ("assets", "ca_file", "cert_file", "key_file"):
        value = getattr(config, name)
        if value:
            values[name] = str((path.resolve().parent / value).resolve())
    return ReceiverConfig(**values)
