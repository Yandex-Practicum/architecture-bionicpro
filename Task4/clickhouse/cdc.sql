CREATE DATABASE IF NOT EXISTS reporting;

CREATE TABLE IF NOT EXISTS reporting.crm_clients_cdc
(
    id UUID,
    identity_subject UUID,
    country_code String,
    deleted UInt8,
    version UInt64
)
ENGINE = ReplacingMergeTree(version)
ORDER BY id;

CREATE TABLE IF NOT EXISTS reporting.crm_prostheses_cdc
(
    id UUID,
    client_id UUID,
    serial_number String,
    model String,
    deleted UInt8,
    version UInt64
)
ENGINE = ReplacingMergeTree(version)
ORDER BY id;

CREATE TABLE IF NOT EXISTS reporting.crm_snapshot_status
(
    source_table LowCardinality(String),
    snapshot LowCardinality(String),
    version UInt64
)
ENGINE = MergeTree
ORDER BY (source_table, version);

CREATE TABLE IF NOT EXISTS reporting.crm_clients_queue (json String)
ENGINE = Kafka
SETTINGS
    kafka_broker_list = 'kafka:9092',
    kafka_topic_list = 'crm_cdc.crm.clients',
    kafka_group_name = 'clickhouse_crm_clients',
    kafka_format = 'JSONAsString',
    kafka_num_consumers = 1;

CREATE TABLE IF NOT EXISTS reporting.crm_prostheses_queue (json String)
ENGINE = Kafka
SETTINGS
    kafka_broker_list = 'kafka:9092',
    kafka_topic_list = 'crm_cdc.crm.prostheses',
    kafka_group_name = 'clickhouse_crm_prostheses',
    kafka_format = 'JSONAsString',
    kafka_num_consumers = 1;

CREATE MATERIALIZED VIEW IF NOT EXISTS reporting.crm_clients_consumer
TO reporting.crm_clients_cdc
AS SELECT
    toUUID(if(JSONExtractString(json, 'op') = 'd', JSONExtractString(json, 'before', 'id'), JSONExtractString(json, 'after', 'id'))) AS id,
    toUUIDOrZero(if(JSONExtractString(json, 'op') = 'd', '', JSONExtractString(json, 'after', 'identity_subject'))) AS identity_subject,
    if(JSONExtractString(json, 'op') = 'd', '', JSONExtractString(json, 'after', 'country_code')) AS country_code,
    JSONExtractString(json, 'op') = 'd' AS deleted,
    _offset AS version
FROM reporting.crm_clients_queue
WHERE JSONExtractString(json, 'op') IN ('r', 'c', 'u', 'd');

CREATE MATERIALIZED VIEW IF NOT EXISTS reporting.crm_prostheses_consumer
TO reporting.crm_prostheses_cdc
AS SELECT
    toUUID(if(JSONExtractString(json, 'op') = 'd', JSONExtractString(json, 'before', 'id'), JSONExtractString(json, 'after', 'id'))) AS id,
    toUUIDOrZero(if(JSONExtractString(json, 'op') = 'd', '', JSONExtractString(json, 'after', 'client_id'))) AS client_id,
    if(JSONExtractString(json, 'op') = 'd', '', JSONExtractString(json, 'after', 'serial_number')) AS serial_number,
    if(JSONExtractString(json, 'op') = 'd', '', JSONExtractString(json, 'after', 'model')) AS model,
    JSONExtractString(json, 'op') = 'd' AS deleted,
    _offset AS version
FROM reporting.crm_prostheses_queue
WHERE JSONExtractString(json, 'op') IN ('r', 'c', 'u', 'd');

CREATE MATERIALIZED VIEW IF NOT EXISTS reporting.crm_clients_snapshot_consumer
TO reporting.crm_snapshot_status
AS SELECT
    'clients' AS source_table,
    JSONExtractString(json, 'source', 'snapshot') AS snapshot,
    _offset AS version
FROM reporting.crm_clients_queue
WHERE JSONExtractString(json, 'op') = 'r';

CREATE MATERIALIZED VIEW IF NOT EXISTS reporting.crm_prostheses_snapshot_consumer
TO reporting.crm_snapshot_status
AS SELECT
    'prostheses' AS source_table,
    JSONExtractString(json, 'source', 'snapshot') AS snapshot,
    _offset AS version
FROM reporting.crm_prostheses_queue
WHERE JSONExtractString(json, 'op') = 'r';

CREATE TABLE IF NOT EXISTS reporting.telemetry_daily
(
    report_date Date,
    prosthesis_id UUID,
    telemetry_events UInt64,
    movements UInt64,
    avg_response_time_ms Float64,
    p95_response_time_ms Float64,
    avg_battery_level_pct Float64,
    min_battery_level_pct Float64,
    avg_signal_quality Float64,
    last_event_at DateTime64(3, 'UTC'),
    updated_at DateTime64(3)
)
ENGINE = ReplacingMergeTree(updated_at)
PARTITION BY toYYYYMM(report_date)
ORDER BY (report_date, prosthesis_id);

CREATE TABLE IF NOT EXISTS reporting.user_prosthesis_daily_cdc
(
    report_date Date,
    user_id UUID,
    prosthesis_id UUID,
    serial_number String,
    model LowCardinality(String),
    country_code LowCardinality(String),
    telemetry_events UInt64,
    movements UInt64,
    avg_response_time_ms Float64,
    p95_response_time_ms Float64,
    avg_battery_level_pct Float64,
    min_battery_level_pct Float64,
    avg_signal_quality Float64,
    last_event_at DateTime64(3, 'UTC'),
    crm_clients_version UInt64,
    crm_prostheses_version UInt64,
    is_metadata UInt8
)
ENGINE = MergeTree
PARTITION BY toYYYYMM(report_date)
ORDER BY (user_id, report_date, prosthesis_id);

DROP VIEW IF EXISTS reporting.user_prosthesis_daily_cdc_mv;

CREATE MATERIALIZED VIEW IF NOT EXISTS reporting.user_prosthesis_daily_cdc_mv
REFRESH EVERY 10 SECOND TO reporting.user_prosthesis_daily_cdc
AS WITH
    coalesce((SELECT max(version) FROM reporting.crm_clients_cdc), 0) AS crm_clients_version,
    coalesce((SELECT max(version) FROM reporting.crm_prostheses_cdc), 0) AS crm_prostheses_version
SELECT
    t.report_date,
    c.identity_subject AS user_id,
    p.id AS prosthesis_id,
    p.serial_number,
    p.model,
    c.country_code,
    t.telemetry_events,
    t.movements,
    t.avg_response_time_ms,
    t.p95_response_time_ms,
    t.avg_battery_level_pct,
    t.min_battery_level_pct,
    t.avg_signal_quality,
    t.last_event_at,
    crm_clients_version,
    crm_prostheses_version,
    0 AS is_metadata
FROM reporting.telemetry_daily AS t FINAL
INNER JOIN
(
    SELECT id, client_id, serial_number, model
    FROM reporting.crm_prostheses_cdc FINAL
    WHERE deleted = 0
) AS p ON p.id = t.prosthesis_id
INNER JOIN
(
    SELECT id, identity_subject, country_code
    FROM reporting.crm_clients_cdc FINAL
    WHERE deleted = 0
) AS c ON c.id = p.client_id
UNION ALL
SELECT
    toDate(0),
    toUUID('00000000-0000-0000-0000-000000000000'),
    toUUID('00000000-0000-0000-0000-000000000000'),
    '',
    '',
    '',
    0,
    0,
    0.,
    0.,
    0.,
    0.,
    0.,
    toDateTime64(0, 3, 'UTC'),
    crm_clients_version,
    crm_prostheses_version,
    1;
