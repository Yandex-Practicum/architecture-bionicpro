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
    def extract_crm() -> list[dict]:
        hook = PostgresHook(postgres_conn_id="crm_db")
        rows = hook.get_records(
            """
            SELECT username, full_name, prosthesis_model, prosthesis_type, device_id
            FROM clients
            """
        )
        return [
            {"username": u, "full_name": f, "model": m, "ptype": t, "device_id": d}
            for u, f, m, t, d in rows
        ]

    @task
    def extract_telemetry(logical_date: pendulum.DateTime) -> dict:
        date_to = logical_date.subtract(days=1).date()
        date_from = date_to.subtract(days=13)          # скользящее окно 14 дней
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
            "counts": [
                {"device_id": d, "day": day.isoformat(), "grips": int(g),
                 "releases": int(r), "mode_switches": int(s)}
                for d, day, g, r, s in counts
            ],
            "modes": modes_by_key,
        }

    @task
    def build_mart(crm_rows: list[dict], telemetry: dict) -> list[dict]:
        rows = []
        for client in crm_rows:
            for c in telemetry["counts"]:
                if c["device_id"] != client["device_id"]:
                    continue
                day = c["day"]
                rows.append({
                    "username": client["username"],
                    "report_date": day,
                    "prosthesis_model": client["model"],
                    "prosthesis_type": client["ptype"],
                    "grips_count": c["grips"],
                    "releases_count": c["releases"],
                    "mode_switches_count": c["mode_switches"],
                    "modes_usage_minutes": telemetry["modes"].get(f"{client['device_id']}|{day}", {}),
                })
        return rows

    @task
    def load_clickhouse(rows: list[dict]) -> None:
        if not rows:
            print("Нет данных для загрузки")
            return

        date_from = min(r["report_date"] for r in rows)
        date_to = max(r["report_date"] for r in rows)
        client = clickhouse_connect.get_client(
            host=os.environ.get("CLICKHOUSE_HOST", "clickhouse"),
            port=int(os.environ.get("CLICKHOUSE_PORT", "8123")),
            username=os.environ.get("CLICKHOUSE_USER", "default"),
            password=os.environ.get("CLICKHOUSE_PASSWORD", ""),
        )
        client.command(
            "ALTER TABLE reports.user_prosthesis_daily DELETE WHERE report_date BETWEEN %(f)s AND %(t)s",
            parameters={"f": date_from, "t": date_to},
            settings={"mutations_sync": 1},
        )
        client.insert(
            "reports.user_prosthesis_daily",
            [
                [
                    r["username"], date.fromisoformat(r["report_date"]),
                    r["prosthesis_model"], r["prosthesis_type"],
                    r["grips_count"], r["releases_count"], r["mode_switches_count"],
                    r["modes_usage_minutes"],
                ]
                for r in rows
            ],
            column_names=[
                "username", "report_date", "prosthesis_model", "prosthesis_type",
                "grips_count", "releases_count", "mode_switches_count", "modes_usage_minutes",
            ],
        )
        print(f"Загружено {len(rows)} строк за {date_from}..{date_to}")

    @task
    def invalidate_s3_cache(rows: list[dict]) -> None:
        if not rows:
            return
        win_from = date.fromisoformat(min(r["report_date"] for r in rows))
        win_to = date.fromisoformat(max(r["report_date"] for r in rows))

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
                    if cf <= win_to and ct >= win_from:   # периоды пересекаются
                        stale.append({"Key": obj["Key"]})
        if stale:
            s3.delete_objects(Bucket=bucket, Delete={"Objects": stale})
        print(f"Инвалидировано {len(stale)} кешей, окно {win_from}..{win_to}")

    crm = extract_crm()
    telemetry = extract_telemetry()
    mart = build_mart(crm, telemetry)
    loaded = load_clickhouse(mart)
    invalidated = invalidate_s3_cache(mart)
    loaded >> invalidated


prosthesis_report_etl()