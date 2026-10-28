-- CRM
CREATE TABLE IF NOT EXISTS crm_clients (
    user_id     VARCHAR(64) PRIMARY KEY,
    full_name   VARCHAR(200) NOT NULL,
    email       VARCHAR(200),
    prosthesis_model VARCHAR(100)
);

-- Telemetry (sensors)
CREATE TABLE IF NOT EXISTS telemetry (
    id          SERIAL PRIMARY KEY,
    user_id     VARCHAR(64) NOT NULL,
    recorded_at TIMESTAMP NOT NULL DEFAULT NOW(),
    steps       INT NOT NULL DEFAULT 0,
    distance_m  FLOAT NOT NULL DEFAULT 0,
    load_kg     FLOAT NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_telemetry_user ON telemetry(user_id);

-- Source data only. The report mart is built in ClickHouse by the Airflow DAG.
INSERT INTO crm_clients (user_id, full_name, email, prosthesis_model) VALUES
    ('prothetic1', 'Prothetic One', 'prothetic1@example.com', 'BP-Walk-X1'),
    ('prothetic2', 'Prothetic Two', 'prothetic2@example.com', 'BP-Walk-X2'),
    ('prothetic3', 'Prothetic Three', 'prothetic3@example.com', 'BP-Run-S1'),
    ('user1', 'User One', 'user1@example.com', 'BP-Basic'),
    ('user2', 'User Two', 'user2@example.com', 'BP-Basic')
ON CONFLICT (user_id) DO NOTHING;

INSERT INTO telemetry (user_id, recorded_at, steps, distance_m, load_kg) VALUES
    ('prothetic1', NOW() - INTERVAL '2 days', 4200, 3100, 12.5),
    ('prothetic1', NOW() - INTERVAL '1 day', 5100, 3800, 13.1),
    ('prothetic1', NOW(), 3900, 2900, 11.8),
    ('prothetic2', NOW() - INTERVAL '1 day', 2800, 2100, 10.2),
    ('prothetic2', NOW(), 3300, 2500, 10.9),
    ('prothetic3', NOW(), 6100, 4500, 14.0),
    ('user1', NOW(), 1500, 1100, 9.5),
    ('user2', NOW() - INTERVAL '3 days', 800, 600, 8.0);
