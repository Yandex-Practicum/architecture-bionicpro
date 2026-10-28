CREATE DATABASE IF NOT EXISTS olap;

CREATE TABLE IF NOT EXISTS olap.report_mart
(
    user_id           String,
    full_name         String,
    email             String,
    prosthesis_model  String,
    total_steps       UInt64,
    total_distance_m  Float64,
    avg_load_kg       Float64,
    sessions_count    UInt64,
    last_activity_at  Nullable(DateTime),
    updated_at        DateTime
)
ENGINE = MergeTree
ORDER BY user_id;
