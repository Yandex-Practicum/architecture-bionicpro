SET allow_experimental_refreshable_materialized_view = 1;

-- Новая витрина отчётности.
CREATE TABLE IF NOT EXISTS reports.user_report_cdc_daily (
    report_date Date,
    user_id String,
    client_id String,
    client_name String,
    prosthesis_id String,
    signals_count UInt64,
    movements_count UInt64,
    is_ready_marker UInt8,
    refreshed_at DateTime64(3, 'UTC')
)
ENGINE = MergeTree
ORDER BY (
    is_ready_marker,
    user_id,
    report_date,
    prosthesis_id
);

-- Витрина целиком обновляется раз в минуту.
-- Без APPEND результат каждого обновления заменяет предыдущий.
CREATE MATERIALIZED VIEW IF NOT EXISTS reports.user_report_cdc_refresh_mv
REFRESH EVERY 1 MINUTE
TO reports.user_report_cdc_daily
AS

-- Отчётные строки: телеметрия + актуальные владельцы из CDC.
SELECT
    telemetry.report_date AS report_date,
    crm.user_id AS user_id,
    crm.client_id AS client_id,
    crm.client_name AS client_name,
    telemetry.prosthesis_id AS prosthesis_id,
    telemetry.signals_count AS signals_count,
    telemetry.movements_count AS movements_count,
    toUInt8(0) AS is_ready_marker,
    now64(3) AS refreshed_at
FROM
(
    -- Используем уже подготовленные суточные показатели.
    -- Старые user_id и client_id здесь не используются.
    SELECT
        report_date,
        prosthesis_id,
        sum(signals_count) AS signals_count,
        sum(movements_count) AS movements_count
    FROM reports.user_report_daily
    WHERE report_date IN
    (
        SELECT report_date
        FROM reports.etl_periods FINAL
        WHERE status = 'ready'
    )
    GROUP BY
        report_date,
        prosthesis_id
) AS telemetry
INNER JOIN
(
    SELECT
        client_id,
        user_id,
        client_name,
        arrayJoin(prosthesis_ids) AS prosthesis_id
    FROM reports.crm_clients_cdc FINAL
    WHERE is_deleted = 0
) AS crm
ON telemetry.prosthesis_id = crm.prosthesis_id

UNION ALL

-- Служебные строки подтверждают готовность дней
-- именно в этом опубликованном снимке витрины.
SELECT
    report_date,
    '' AS user_id,
    '' AS client_id,
    '' AS client_name,
    '' AS prosthesis_id,
    toUInt64(0) AS signals_count,
    toUInt64(0) AS movements_count,
    toUInt8(1) AS is_ready_marker,
    now64(3) AS refreshed_at
FROM reports.etl_periods FINAL
WHERE status = 'ready';