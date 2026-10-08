CREATE TABLE telemetry_messages(
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    device_id TEXT NOT NULL,
    sequence_no BIGINT NOT NULL,
    event_time TIMESTAMPTZ NOT NULL,
    battery_percent DOUBLE PRECISION,
    payload JSONB NOT NULL,
    received_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP

    CHECK (device_id <> ''),
    CHECK (sequence_no >= 0),
    CHECK (battery_percent BETWEEN 0 AND 100),
    CONSTRAINT telemetry_messages_event_key UNIQUE (device_id, event_time, sequence_no)
);