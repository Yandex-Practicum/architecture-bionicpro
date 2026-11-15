import base64
import json
import os
import secrets
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from airflow.decorators import dag, task
from airflow.hooks.base import BaseHook
from airflow.operators.python import get_current_context
from airflow.providers.postgres.hooks.postgres import PostgresHook


DDL = """
CREATE TABLE IF NOT EXISTS reporting.telemetry_daily_stage
(
    run_id String,
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
    loaded_at DateTime64(3) DEFAULT now64(3)
)
ENGINE = MergeTree
ORDER BY (run_id, report_date, prosthesis_id)
TTL toDateTime(loaded_at) + INTERVAL 2 DAY DELETE;
"""


TELEMETRY_SQL = """
SELECT prosthesis_id::text AS prosthesis_id,
       date_trunc('day', recorded_at AT TIME ZONE 'UTC')::date AS report_date,
       count(*) AS telemetry_events,
       count(*) FILTER (WHERE movement_detected) AS movements,
       avg(response_time_ms)::float8 AS avg_response_time_ms,
       percentile_cont(0.95) WITHIN GROUP (ORDER BY response_time_ms)::float8 AS p95_response_time_ms,
       avg(battery_level_pct)::float8 AS avg_battery_level_pct,
       min(battery_level_pct)::float8 AS min_battery_level_pct,
       avg(signal_quality)::float8 AS avg_signal_quality,
       max(recorded_at) AS last_event_at
FROM telemetry.events
WHERE recorded_at >= %s AND recorded_at < %s
GROUP BY prosthesis_id, date_trunc('day', recorded_at AT TIME ZONE 'UTC')
"""


class ClickHouseHTTP:
    def __init__(self):
        connection = BaseHook.get_connection("clickhouse_http")
        scheme = "https" if connection.conn_type == "https" else "http"
        self.url = f"{scheme}://{connection.host}:{connection.port or 8123}/"
        credentials = f"{connection.login or 'default'}:{connection.password or ''}"
        self.authorization = "Basic " + base64.b64encode(credentials.encode()).decode()

    def execute(self, query, data=None):
        url = self.url + "?" + urlencode({"query": query})
        request = Request(url, data=data, method="POST")
        request.add_header("Authorization", self.authorization)
        try:
            with urlopen(request, timeout=120) as response:
                return response.read().decode()
        except HTTPError as error:
            raise RuntimeError(error.read().decode()) from error

    def insert(self, table, rows):
        payload = "\n".join(json.dumps(row, default=str) for row in rows).encode()
        self.execute(
            f"INSERT INTO {table} SETTINGS date_time_input_format = 'best_effort' FORMAT JSONEachRow",
            payload,
        )


def escaped(value):
    return value.replace("\\", "\\\\").replace("'", "\\'")


def reporting_interval(context):
    end = context["data_interval_end"].replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    return end - timedelta(days=1), end


def copy_postgres_query(connection_id, query, params, table, run_id):
    hook = PostgresHook(postgres_conn_id=connection_id)
    clickhouse = ClickHouseHTTP()
    with hook.get_conn() as connection, connection.cursor(name="reports_etl") as cursor:
        cursor.itersize = 5000
        cursor.execute(query, params)
        while rows := cursor.fetchmany(5000):
            columns = [description.name for description in cursor.description]
            clickhouse.insert(
                table,
                [dict(zip(("run_id", *columns), (run_id, *row))) for row in rows],
            )


@dag(
    dag_id="reports_daily_mart",
    schedule="0 2 * * *",
    start_date=datetime(2026, 1, 1, tzinfo=timezone.utc),
    catchup=False,
    max_active_runs=1,
    default_args={"retries": 2},
    tags=["reports", "etl"],
)
def reports_daily_mart():
    @task
    def prepare_olap():
        clickhouse = ClickHouseHTTP()
        for statement in filter(str.strip, DDL.split(";")):
            clickhouse.execute(statement)

    @task
    def extract_telemetry():
        context = get_current_context()
        run_id = context["run_id"]
        start, end = reporting_interval(context)
        clickhouse = ClickHouseHTTP()
        clickhouse.execute(
            f"ALTER TABLE reporting.telemetry_daily_stage DELETE WHERE run_id = '{escaped(run_id)}' SETTINGS mutations_sync = 1"
        )
        copy_postgres_query(
            "telemetry_postgres",
            TELEMETRY_SQL,
            (start, end),
            "reporting.telemetry_daily_stage",
            run_id,
        )

    @task
    def build_mart():
        context = get_current_context()
        run_id = escaped(context["run_id"])
        clickhouse = ClickHouseHTTP()
        clickhouse.execute(
            f"""
            INSERT INTO reporting.telemetry_daily
            SELECT t.report_date, t.prosthesis_id, t.telemetry_events, t.movements,
                   t.avg_response_time_ms, t.p95_response_time_ms,
                   t.avg_battery_level_pct, t.min_battery_level_pct,
                   t.avg_signal_quality, t.last_event_at, now64(3)
            FROM reporting.telemetry_daily_stage t
            WHERE t.run_id = '{run_id}'
            """
        )
        inserted_at = clickhouse.execute("SELECT toUnixTimestamp(now())").strip()
        for _ in range(30):
            time.sleep(1)
            refreshed = clickhouse.execute(
                "SELECT count() "
                "FROM system.view_refreshes "
                "WHERE database = 'reporting' "
                "AND view = 'user_prosthesis_daily_cdc_mv' "
                f"AND toUnixTimestamp(last_refresh_time) > {inserted_at} "
                "AND last_success_time >= last_refresh_time"
            ).strip()
            if refreshed == "1":
                break
        else:
            raise RuntimeError("reporting materialized view refresh timed out")

    @task
    def publish_cache_version():
        version = secrets.token_hex(8)
        request = Request(
            f"{os.environ['REPORTS_CACHE_URL'].rstrip('/')}/{version}",
            method="POST",
            headers={"X-Internal-Token": os.environ["INTERNAL_CACHE_TOKEN"]},
        )
        with urlopen(request, timeout=30):
            pass

    @task
    def cleanup():
        run_id = escaped(get_current_context()["run_id"])
        clickhouse = ClickHouseHTTP()
        clickhouse.execute(
            f"ALTER TABLE reporting.telemetry_daily_stage DELETE WHERE run_id = '{run_id}' SETTINGS mutations_sync = 1"
        )

    prepared = prepare_olap()
    telemetry = extract_telemetry()
    prepared >> telemetry
    cleanup_task = cleanup()
    mart = build_mart()
    publish_cache = publish_cache_version()
    telemetry >> mart >> publish_cache >> cleanup_task


reports_daily_mart()
