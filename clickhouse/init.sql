CREATE DATABASE IF NOT EXISTS reports;

CREATE TABLE IF NOT EXISTS reports.user_prosthesis_daily (
    username String,
    report_date Date,
    prosthesis_model String,
    prosthesis_type String,
    grips_count UInt32,
    releases_count UInt32,
    mode_switches_count UInt32,
    modes_usage_minutes Map(String, UInt32)
    ) ENGINE = ReplacingMergeTree
        ORDER BY (username, report_date);

-- Задание 4

CREATE TABLE IF NOT EXISTS reports.crm_clients_kafka
(
    client_id Int32,
    username String,
    full_name String,
    prosthesis_model String,
    prosthesis_type String,
    device_id String
)
    ENGINE = Kafka
    SETTINGS
    kafka_broker_list = 'kafka:9092',
    kafka_topic_list = 'crm.public.clients',
    kafka_group_name = 'clickhouse_crm_mirror',
    kafka_format = 'JSONEachRow',
    kafka_num_consumers = 1;

CREATE TABLE IF NOT EXISTS reports.crm_clients
(
    client_id Int32,
    username String,
    full_name String,
    prosthesis_model String,
    prosthesis_type String,
    device_id String
)
    ENGINE = ReplacingMergeTree
    ORDER BY client_id;

CREATE MATERIALIZED VIEW IF NOT EXISTS reports.crm_clients_mv
TO reports.crm_clients
AS
SELECT client_id, username, full_name, prosthesis_model, prosthesis_type, device_id
FROM reports.crm_clients_kafka;

-- Агрегаты
CREATE TABLE IF NOT EXISTS reports.telemetry_daily
(
    device_id String,
    report_date Date,
    grips_count UInt32,
    releases_count UInt32,
    mode_switches_count UInt32,
    modes_usage_minutes Map(String, UInt32)
    )
    ENGINE = ReplacingMergeTree
    ORDER BY (device_id, report_date);

-- Витрина
CREATE MATERIALIZED VIEW IF NOT EXISTS reports.user_prosthesis_daily_mv
TO reports.user_prosthesis_daily
AS
SELECT
    c.username AS username,
    t.report_date AS report_date,
    c.prosthesis_model AS prosthesis_model,
    c.prosthesis_type AS prosthesis_type,
    t.grips_count AS grips_count,
    t.releases_count AS releases_count,
    t.mode_switches_count AS mode_switches_count,
    t.modes_usage_minutes AS modes_usage_minutes
FROM reports.telemetry_daily AS t
         INNER JOIN
     (
         SELECT client_id, username, prosthesis_model, prosthesis_type, device_id
         FROM reports.crm_clients FINAL
     ) AS c ON c.device_id = t.device_id;