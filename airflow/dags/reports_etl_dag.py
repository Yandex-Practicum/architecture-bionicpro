"""ETL: CRM + telemetry (Postgres) → ClickHouse report_mart. Daily at 02:00."""
import os
from datetime import datetime, timedelta

from airflow import DAG
from airflow.operators.python import PythonOperator

default_args = {
    "owner": "bionicpro",
    "depends_on_past": False,
    "retries": 1,
    "retry_delay": timedelta(minutes=5),
}

EXTRACT_SQL = """
SELECT
    c.user_id,
    c.full_name,
    COALESCE(c.email, ''),
    COALESCE(c.prosthesis_model, ''),
    COALESCE(SUM(t.steps), 0)::bigint,
    COALESCE(SUM(t.distance_m), 0)::float,
    COALESCE(AVG(t.load_kg), 0)::float,
    COUNT(t.id)::bigint,
    MAX(t.recorded_at)
FROM crm_clients c
LEFT JOIN telemetry t ON t.user_id = c.user_id
GROUP BY c.user_id, c.full_name, c.email, c.prosthesis_model
"""


def build_report_mart(**_):
    import clickhouse_connect
    import psycopg2

    conn = psycopg2.connect(os.environ["SOURCE_DSN"])
    try:
        with conn.cursor() as cur:
            cur.execute(EXTRACT_SQL)
            rows = cur.fetchall()
    finally:
        conn.close()

    now = datetime.utcnow().replace(microsecond=0)
    data = []
    for user_id, full_name, email, model, steps, distance, load, sessions, last_at in rows:
        if last_at is not None:
            last_at = last_at.replace(tzinfo=None, microsecond=0)
        data.append(
            (
                user_id,
                full_name,
                email,
                model,
                int(steps),
                float(distance),
                float(load),
                int(sessions),
                last_at,
                now,
            )
        )

    client = clickhouse_connect.get_client(
        host=os.environ.get("CLICKHOUSE_HOST", "clickhouse"),
        port=int(os.environ.get("CLICKHOUSE_PORT", "8123")),
        username=os.environ.get("CLICKHOUSE_USER", "default"),
        password=os.environ.get("CLICKHOUSE_PASSWORD", ""),
        database=os.environ.get("CLICKHOUSE_DATABASE", "olap"),
    )
    client.command("TRUNCATE TABLE report_mart")
    if data:
        client.insert(
            "report_mart",
            data,
            column_names=[
                "user_id",
                "full_name",
                "email",
                "prosthesis_model",
                "total_steps",
                "total_distance_m",
                "avg_load_kg",
                "sessions_count",
                "last_activity_at",
                "updated_at",
            ],
        )


with DAG(
    dag_id="reports_etl",
    default_args=default_args,
    description="CRM + telemetry → ClickHouse report_mart",
    schedule="0 2 * * *",
    start_date=datetime(2024, 1, 1),
    catchup=False,
    is_paused_upon_creation=False,
    tags=["reports", "etl", "clickhouse"],
) as dag:
    PythonOperator(
        task_id="build_report_mart",
        python_callable=build_report_mart,
    )
