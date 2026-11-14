import clickhouse_connect
from datetime import date
import os
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
        target_date = logical_date.subtract(days=1).date()
        hook = PostgresHook(postgres_conn_id="telemetry_db")

        counts = hook.get_records(
            """
            SELECT device_id,
                   COUNT(*) FILTER (WHERE event_type = 'grip')        AS grips,
                   COUNT(*) FILTER (WHERE event_type = 'release')     AS releases,
                   COUNT(*) FILTER (WHERE event_type = 'mode_switch') AS mode_switches
            FROM telemetry_events
            WHERE ts::date = %(d)s
            GROUP BY device_id
            """,
            parameters={"d": target_date},
        )
        modes = hook.get_records(
            """
            SELECT device_id, mode, COALESCE(SUM(duration_seconds), 0) / 60 AS minutes
            FROM telemetry_events
            WHERE ts::date = %(d)s AND event_type = 'mode_switch' AND mode IS NOT NULL
            GROUP BY device_id, mode
            """,
            parameters={"d": target_date},
        )

        modes_by_device: dict[str, dict[str, int]] = {}
        for device_id, mode, minutes in modes:
            modes_by_device.setdefault(device_id, {})[mode] = int(minutes)

        return {
            "target_date": target_date.isoformat(),
            "counts": [
                {"device_id": d, "grips": int(g), "releases": int(r), "mode_switches": int(s)}
                for d, g, r, s in counts
            ],
            "modes": modes_by_device,
        }

    @task
    def build_mart(crm_rows: list[dict], telemetry: dict) -> list[dict]:
        by_device = {c["device_id"]: c for c in telemetry["counts"]}
        report_date = telemetry["target_date"]
        rows = []
        for client in crm_rows:
            t = by_device.get(client["device_id"])
            if t is None:
                continue
            rows.append({
                "username": client["username"],
                "report_date": report_date,
                "prosthesis_model": client["model"],
                "prosthesis_type": client["ptype"],
                "grips_count": t["grips"],
                "releases_count": t["releases"],
                "mode_switches_count": t["mode_switches"],
                "modes_usage_minutes": telemetry["modes"].get(client["device_id"], {}),
            })
        return rows

    @task
    def load_clickhouse(rows: list[dict]) -> None:
        if not rows:
            print("Нет данных для загрузки")
            return
        report_date = rows[0]["report_date"]
        client = clickhouse_connect.get_client(
            host=os.environ.get("CLICKHOUSE_HOST", "clickhouse"),
            port=int(os.environ.get("CLICKHOUSE_PORT", "8123")),
            username=os.environ.get("CLICKHOUSE_USER", "default"),
            password=os.environ.get("CLICKHOUSE_PASSWORD", ""),
        )
        client.command(
            "ALTER TABLE reports.user_prosthesis_daily DELETE WHERE report_date = %(d)s",
            parameters={"d": report_date},
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
        print(f"Загружено {len(rows)} строк за {report_date}")

    load_clickhouse(build_mart(extract_crm(), extract_telemetry()))


prosthesis_report_etl()