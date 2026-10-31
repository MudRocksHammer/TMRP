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
CREATE INDEX IF NOT EXISTS power_telemetry_history_page
    ON power_telemetry (device_id, event_time, boot_id, sequence_no);
CREATE TABLE IF NOT EXISTS power_telemetry_rejections (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    received_at timestamptz NOT NULL,
    topic varchar(512) NOT NULL,
    reason text NOT NULL,
    payload_sha256 char(64) NOT NULL,
    payload_bytes bigint NOT NULL
);
CREATE TABLE IF NOT EXISTS device_commands (
    device_id varchar(128) NOT NULL,
    command_id varchar(128) NOT NULL,
    request jsonb NOT NULL,
    payload jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    expires_at timestamptz NOT NULL,
    next_attempt_at timestamptz NOT NULL DEFAULT now(),
    publish_attempts integer NOT NULL DEFAULT 0,
    result jsonb,
    result_received_at timestamptz,
    PRIMARY KEY (device_id, command_id)
);
CREATE INDEX IF NOT EXISTS device_commands_dispatch
    ON device_commands (next_attempt_at) WHERE result IS NULL OR result->>'status' = 'accepted';
