CREATE TABLE IF NOT EXISTS power_telemetry (
    device_id varchar(128) NOT NULL,
    boot_id varchar(128) NOT NULL,
    sequence_no bigint NOT NULL CHECK (sequence_no >= 0),
    event_time timestamptz NOT NULL,
    received_at timestamptz NOT NULL,
    topic text NOT NULL,
    payload jsonb NOT NULL CHECK (jsonb_typeof(payload) = 'object'),
    PRIMARY KEY (device_id, boot_id, sequence_no)
);
CREATE INDEX IF NOT EXISTS power_telemetry_device_time
    ON power_telemetry (device_id, event_time DESC);
CREATE TABLE IF NOT EXISTS power_telemetry_rejections (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    received_at timestamptz NOT NULL,
    topic varchar(512) NOT NULL,
    reason text NOT NULL,
    payload_sha256 char(64) NOT NULL,
    payload_bytes bigint NOT NULL
);
