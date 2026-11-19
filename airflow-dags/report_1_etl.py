import os
import re
from datetime import date

import boto3
import clickhouse_connect
import pendulum
from airflow.decorators import dag, task
from airflow.providers.postgres.hooks.postgres import PostgresHook


@dag(
    dag_id="prosthesis_report_etl",
    schedule="*/10 * * * *",
    start_date=pendulum.datetime(2026, 1, 1),
    catchup=False,
    tags=["bionicpro"],
)
def prosthesis_report_etl():

    @task
    def extract_telemetry(logical_date: pendulum.DateTime) -> dict:
        date_to = logical_date.subtract(days=1).date()
        date_from = date_to.subtract(days=13)
        hook = PostgresHook(postgres_conn_id="telemetry_db")

        counts = hook.get_records(
            """
            SELECT device_id, ts::date AS day,
                   COUNT(*) FILTER (WHERE event_type = 'grip')        AS grips,
                   COUNT(*) FILTER (WHERE event_type = 'release')     AS releases,
                   COUNT(*) FILTER (WHERE event_type = 'mode_switch') AS mode_switches
            FROM telemetry_events
            WHERE ts::date BETWEEN %(f)s AND %(t)s
            GROUP BY device_id, ts::date
            """,
            parameters={"f": date_from, "t": date_to},
        )
        modes = hook.get_records(
            """
            SELECT device_id, ts::date AS day, mode,
                   COALESCE(SUM(duration_seconds), 0) / 60 AS minutes
            FROM telemetry_events
            WHERE ts::date BETWEEN %(f)s AND %(t)s
              AND event_type = 'mode_switch' AND mode IS NOT NULL
            GROUP BY device_id, ts::date, mode
            """,
            parameters={"f": date_from, "t": date_to},
        )

        modes_by_key: dict[str, dict[str, int]] = {}
        for device_id, day, mode, minutes in modes:
            modes_by_key.setdefault(f"{device_id}|{day.isoformat()}", {})[mode] = int(minutes)

        return {
            "window": {"from": date_from.isoformat(), "to": date_to.isoformat()},
            "rows": [
                {"device_id": str(d), "day": day.isoformat(), "grips": int(g),
                 "releases": int(r), "mode_switches": int(s),
                 "modes_usage_minutes": modes_by_key.get(f"{d}|{day.isoformat()}", {})}
                for d, day, g, r, s in counts
            ],
        }

    @task
    def load_telemetry_daily(telemetry: dict) -> dict:
        client = clickhouse_connect.get_client(
            host=os.environ.get("CLICKHOUSE_HOST", "clickhouse"),
            port=int(os.environ.get("CLICKHOUSE_PORT", "8123")),
            username=os.environ.get("CLICKHOUSE_USER", "default"),
            password=os.environ.get("CLICKHOUSE_PASSWORD", ""),
        )
        date_from = telemetry["window"]["from"]
        date_to = telemetry["window"]["to"]

        for table in ("reports.telemetry_daily", "reports.user_prosthesis_daily"):
            client.command(
                f"ALTER TABLE {table} DELETE WHERE report_date BETWEEN %(f)s AND %(t)s",
                parameters={"f": date_from, "t": date_to},
                settings={"mutations_sync": 1},
            )

        rows = telemetry["rows"]
        if rows:
            client.insert(
                "reports.telemetry_daily",
                [
                    [r["device_id"], date.fromisoformat(r["day"]),
                     r["grips"], r["releases"], r["mode_switches"],
                     r["modes_usage_minutes"]]
                    for r in rows
                ],
                column_names=[
                    "device_id", "report_date",
                    "grips_count", "releases_count", "mode_switches_count",
                    "modes_usage_minutes",
                ],
            )
        print(f"Загружено {len(rows)} агрегатов за {date_from}..{date_to}")
        return telemetry["window"]

    @task
    def invalidate_s3_cache(window: dict) -> None:
        win_from = date.fromisoformat(window["from"])
        win_to = date.fromisoformat(window["to"])

        s3 = boto3.client(
            "s3",
            endpoint_url=os.environ["S3_ENDPOINT_URL"],
            aws_access_key_id=os.environ["S3_ACCESS_KEY"],
            aws_secret_access_key=os.environ["S3_SECRET_KEY"],
            region_name="garage",
        )
        bucket = os.environ.get("S3_BUCKET", "reports")

        stale = []
        paginator = s3.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=bucket):
            for obj in page.get("Contents", []):
                m = re.search(r"(\d{4}-\d{2}-\d{2})_(\d{4}-\d{2}-\d{2})_(.+)\.json$", obj["Key"])
                if m:
                    cf, ct = date.fromisoformat(m[1]), date.fromisoformat(m[2])
                    if cf <= win_to and ct >= win_from:
                        stale.append({"Key": obj["Key"]})
        if stale:
            s3.delete_objects(Bucket=bucket, Delete={"Objects": stale})
        print(f"Инвалидировано {len(stale)} кешей, окно {win_from}..{win_to}")

    telemetry = extract_telemetry()
    window = load_telemetry_daily(telemetry)
    invalidate_s3_cache(window)


prosthesis_report_etl()