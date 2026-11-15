WITH
    (SELECT count() FROM reporting.crm_clients_cdc FINAL WHERE deleted = 0) AS clients,
    (SELECT count() FROM reporting.crm_prostheses_cdc FINAL WHERE deleted = 0) AS prostheses,
    (
        SELECT count()
        FROM reporting.crm_snapshot_status
        WHERE source_table = 'clients'
          AND snapshot IN ('last_in_data_collection', 'last')
    ) AS clients_snapshot_done,
    (
        SELECT count()
        FROM reporting.crm_snapshot_status
        WHERE source_table = 'prostheses'
          AND snapshot IN ('last_in_data_collection', 'last')
    ) AS prostheses_snapshot_done,
    (
        SELECT max(crm_clients_version)
        FROM reporting.user_prosthesis_daily_cdc
        WHERE is_metadata = 1
    ) AS report_clients_version,
    (
        SELECT max(crm_prostheses_version)
        FROM reporting.user_prosthesis_daily_cdc
        WHERE is_metadata = 1
    ) AS report_prostheses_version,
    (SELECT max(version) FROM reporting.crm_clients_cdc) AS clients_version,
    (SELECT max(version) FROM reporting.crm_prostheses_cdc) AS prostheses_version
SELECT clients > 0
   AND prostheses > 0
   AND clients_snapshot_done > 0
   AND prostheses_snapshot_done > 0
   AND report_clients_version = clients_version
   AND report_prostheses_version = prostheses_version;
