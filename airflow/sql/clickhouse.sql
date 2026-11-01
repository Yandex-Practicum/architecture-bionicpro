CREATE DATABASE IF NOT EXISTS reports;

-- Связи клиентов и их протезов из CRM.
CREATE TABLE IF NOT EXISTS reports.crm_stage (
    client_id String,
    user_id String,
    prosthesis_id String
)
ENGINE = MergeTree
ORDER BY prosthesis_id;

-- Телеметрия за обрабатываемые сутки.
CREATE TABLE IF NOT EXISTS reports.telemetry_stage (
    event_id UInt64,
    prosthesis_id String,
    occurred_at DateTime64(3, 'UTC'),
    event_type LowCardinality(String)
)
ENGINE = MergeTree
ORDER BY (prosthesis_id, occurred_at, event_id);

-- Готовая дневная витрина для API отчётов.
CREATE TABLE IF NOT EXISTS reports.user_report_daily (
    report_date Date,
    user_id String,
    client_id String,
    prosthesis_id String,
    signals_count UInt64,
    movements_count UInt64
)
ENGINE = MergeTree
PARTITION BY report_date
ORDER BY (user_id, report_date, prosthesis_id);

-- Промежуточный результат перед публикацией готового дня.
CREATE TABLE IF NOT EXISTS reports.report_daily_stage
AS reports.user_report_daily;

-- Дни, которые Airflow успешно обработал и опубликовал.
CREATE TABLE IF NOT EXISTS reports.etl_periods (
    report_date Date,
    status Enum8('ready' = 1),
    completed_at DateTime64(3, 'UTC')
)
ENGINE = ReplacingMergeTree(completed_at)
ORDER BY report_date;