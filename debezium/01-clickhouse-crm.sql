CREATE DATABASE IF NOT EXISTS reports;

-- Версии строк CRM, полученные через CDC.
CREATE TABLE IF NOT EXISTS reports.crm_clients_cdc (
    client_id String,
    user_id String,
    client_name String,
    prosthesis_ids Array(String),
    is_deleted UInt8,
    version UInt64
)
ENGINE = ReplacingMergeTree(version)
ORDER BY client_id;

-- Источник событий Kafka.
-- JSONAsString сохраняет событие Debezium целиком в одной строке.
CREATE TABLE IF NOT EXISTS reports.crm_clients_kafka (
    event String
)

ENGINE = Kafka
SETTINGS
    kafka_broker_list = 'kafka:9092',
    kafka_topic_list = 'crm.public.crm_clients',
    kafka_group_name = 'bionicpro-clickhouse-crm-v1',
    kafka_format = 'JSONAsString',
    kafka_num_consumers = 1;

-- Автоматический разбор событий и запись версий строк.
CREATE MATERIALIZED VIEW IF NOT EXISTS reports.crm_clients_ingest_mv
TO reports.crm_clients_cdc
AS
SELECT
    JSONExtractString(row_data, 'client_id') AS client_id,
    JSONExtractString(row_data, 'user_id') AS user_id,
    JSONExtractString(row_data, 'client_name') AS client_name,
    JSONExtract(
        row_data,
        'prosthesis_ids',
        'Array(String)'
    ) AS prosthesis_ids,
    toUInt8(JSONExtractString(event, 'op') = 'd') AS is_deleted,
    JSONExtractUInt(event, 'source', 'lsn') AS version
FROM
(
    SELECT
        event,
        if(
            JSONExtractString(event, 'op') = 'd',
            JSONExtractRaw(event, 'before'),
            JSONExtractRaw(event, 'after')
        ) AS row_data
    FROM reports.crm_clients_kafka
    WHERE JSONExtractString(event, 'op') IN ('r', 'c', 'u', 'd')
);