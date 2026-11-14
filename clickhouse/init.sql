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