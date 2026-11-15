CREATE SCHEMA telemetry;

CREATE TABLE telemetry.events (
    id BIGSERIAL PRIMARY KEY,
    prosthesis_id UUID NOT NULL,
    recorded_at TIMESTAMPTZ NOT NULL,
    movement_detected BOOLEAN NOT NULL,
    response_time_ms DOUBLE PRECISION NOT NULL,
    battery_level_pct DOUBLE PRECISION NOT NULL,
    signal_quality DOUBLE PRECISION NOT NULL
);

CREATE INDEX telemetry_events_period_idx
    ON telemetry.events (recorded_at, prosthesis_id);

INSERT INTO telemetry.events
    (prosthesis_id, recorded_at, movement_detected, response_time_ms, battery_level_pct, signal_quality)
VALUES
    ('bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbb1', CURRENT_DATE - INTERVAL '1 day' + TIME '10:00', true, 82, 90, 0.94),
    ('bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbb1', CURRENT_DATE - INTERVAL '1 day' + TIME '10:01', true, 105, 89, 0.88),
    ('bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbb1', CURRENT_DATE - INTERVAL '1 day' + TIME '10:02', false, 96, 88, 0.91),
    ('bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbb2', CURRENT_DATE - INTERVAL '1 day' + TIME '11:00', true, 73, 78, 0.96),
    ('bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbb2', CURRENT_DATE - INTERVAL '1 day' + TIME '11:01', true, 79, 77, 0.95),
    ('bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbb3', CURRENT_DATE - INTERVAL '1 day' + TIME '12:00', true, 110, 65, 0.84),
    ('bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbb3', CURRENT_DATE - INTERVAL '1 day' + TIME '12:01', false, 125, 64, 0.80);
