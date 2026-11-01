CREATE VIEW IF NOT EXISTS reports.crm_current_prostheses
AS
SELECT
    client_id,
    user_id,
    arrayJoin(prosthesis_ids) AS prosthesis_id
FROM reports.crm_clients_cdc FINAL
WHERE is_deleted = 0;