CREATE TABLE telemetry_events (
    event_id bigint PRIMARY KEY,
    prosthesis_id text NOT NULL,
    occurred_at timestamptz NOT NULL,
    event_type text NOT NULL
        CHECK (event_type IN ('signal', 'movement'))
);

CREATE INDEX telemetry_events_occurred_at_idx
    ON telemetry_events (occurred_at);

-- Время событий указано в UTC.
-- 30 октября по Москве:
-- [2026-10-29 21:00:00+00, 2026-10-30 21:00:00+00).

INSERT INTO telemetry_events (
    event_id,
    prosthesis_id,
    occurred_at,
    event_type
)
VALUES
    -- До начала отчётного дня: не попадёт в отчёт за 30 октября.
    (1, 'P001', '2026-10-29 20:59:59+00', 'signal'),

    -- Точное начало отчётного дня: попадёт в отчёт.
    (2, 'P001', '2026-10-29 21:00:00+00', 'signal'),

    -- Остальные события отчётного дня.
    (3, 'P001', '2026-10-30 08:00:00+00', 'signal'),
    (4, 'P001', '2026-10-30 09:00:00+00', 'signal'),
    (5, 'P001', '2026-10-30 10:00:00+00', 'movement'),
    (6, 'P001', '2026-10-30 11:00:00+00', 'movement'),

    (7, 'P002', '2026-10-30 08:00:00+00', 'signal'),
    (8, 'P002', '2026-10-30 09:00:00+00', 'movement'),

    (9, 'P003', '2026-10-30 08:00:00+00', 'signal'),
    (10, 'P003', '2026-10-30 09:00:00+00', 'signal'),
    (11, 'P003', '2026-10-30 10:00:00+00', 'movement'),

    -- Начало следующего дня: не попадёт в отчёт за 30 октября.
    (12, 'P001', '2026-10-30 21:00:00+00', 'signal');