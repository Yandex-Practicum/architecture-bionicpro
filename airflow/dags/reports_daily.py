from datetime import timedelta

import pendulum
from airflow.decorators import dag, task
from airflow.operators.python import get_current_context

import reports_etl


@dag(
    dag_id="reports_daily",
    schedule="0 0 * * *",
    start_date=pendulum.datetime(
        2026, 1, 1,
        tz="Europe/Moscow",
    ),
    catchup=False,
    max_active_runs=1,
    default_args={
        "retries": 2,
        "retry_delay": timedelta(minutes=1),
    },
    tags=["bionicpro", "reports"],
)
def reports_daily():
    @task
    def prepare_tables():
        reports_etl.initialize()

    @task
    def extract_telemetry():
        context = get_current_context()

        reports_etl.load_telemetry(
            context["data_interval_start"],
            context["data_interval_end"],
        )

    @task
    def prepare_mart():
        context = get_current_context()

        day = (
            context["data_interval_start"]
            .in_timezone("Europe/Moscow")
            .date()
        )

        reports_etl.publish(day.isoformat())

    tables = prepare_tables()
    telemetry = extract_telemetry()
    mart = prepare_mart()

    tables >> telemetry >> mart


reports_daily()