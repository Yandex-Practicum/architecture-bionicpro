CREATE TABLE telemetry_events (
    id BIGSERIAL PRIMARY KEY,
    device_id VARCHAR(64) NOT NULL,
    ts TIMESTAMP NOT NULL,
    event_type VARCHAR(32) NOT NULL,
    mode VARCHAR(32),
    duration_seconds INTEGER
);

INSERT INTO telemetry_events (device_id, ts, event_type, mode, duration_seconds)
SELECT 'd67d279a-b64a-4646-8ea6-4a562fbb960e',
    now() - interval '1 day' + (g || ' minutes')::interval,
    (ARRAY['grip','release','mode_switch'])[1 + g % 3],
    (ARRAY['grip','power','precision'])[1 + g % 3],
    30 + (g % 300)
FROM generate_series(1, 200) g;