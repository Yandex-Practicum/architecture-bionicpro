CREATE TABLE telemetry_events (
                                  id BIGSERIAL PRIMARY KEY,
                                  event_id UUID NOT NULL UNIQUE,
                                  device_id VARCHAR(64) NOT NULL,
                                  ts TIMESTAMP NOT NULL,
                                  event_type VARCHAR(32) NOT NULL,
                                  mode VARCHAR(32),
                                  duration_seconds INTEGER
);

INSERT INTO telemetry_events (event_id, device_id, ts, event_type, mode, duration_seconds)
SELECT md5(d.device_id || ':' || day_off || ':' || g)::uuid,
    d.device_id,
       (now()::date - day_off) + (g * 5 || ' minutes')::interval,
    (ARRAY['grip','release','mode_switch'])[1 + (g % 3)],
       (ARRAY['power','precision','auto'])[1 + ((g + day_off) % 3)],
       20 + ((g * 7 + day_off * 13) % 280)
FROM (VALUES
    ('d67d279a-b64a-4646-8ea6-4a562fbb960e', 14),   -- prothetic1
    ('4d070f89-5fd1-4853-a7cf-66be63f27217', 3)     -- prothetic2
    ) AS d(device_id, days)
    CROSS JOIN LATERAL generate_series(1, d.days) AS day_off
    CROSS JOIN LATERAL generate_series(1, 60 + (day_off % 5) * 20) AS g
ON CONFLICT (event_id) DO NOTHING;