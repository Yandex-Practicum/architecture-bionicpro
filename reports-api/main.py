import os
from datetime import date
import requests
from fastapi import Depends, FastAPI, HTTPException, Query
from auth import require_user
from storage import (
    report_exists,
    report_key,
    report_url,
    save_report,
)

app = FastAPI(title="BionicPRO Reports API")

CLICKHOUSE_URL = os.environ.get(
    "CLICKHOUSE_URL",
    "http://clickhouse:8123",
)
CLICKHOUSE_USER = os.environ.get(
    "CLICKHOUSE_USER",
    "reports",
)
CLICKHOUSE_PASSWORD = os.environ["CLICKHOUSE_PASSWORD"]


def query_clickhouse(sql, parameters):
    """Выполняет параметризованный запрос к ClickHouse."""
    try:
        response = requests.post(
            CLICKHOUSE_URL,
            auth=(CLICKHOUSE_USER, CLICKHOUSE_PASSWORD),
            params=parameters,
            data=(sql + "\nFORMAT JSON").encode("utf-8"),
            timeout=30,
        )
        response.raise_for_status()
        return response.json()["data"]

    except (
        requests.RequestException,
        ValueError,
        KeyError,
        TypeError,
    ):
        raise HTTPException(
            status_code=502,
            detail="Не удалось получить данные из ClickHouse",
        ) from None


@app.get("/reports")
def get_report(
    date_from: date = Query(),
    date_to: date = Query(),
    user_id: str = Depends(require_user),
):
    if date_from > date_to:
        raise HTTPException(
            status_code=400,
            detail="date_from не может быть позже date_to",
        )

    key = report_key(
        user_id,
        date_from.isoformat(),
        date_to.isoformat(),
    )

    if report_exists(key):
        return {
            "report_url": report_url(key),
        }

    parameters = {
        "param_user_id": user_id,
        "param_date_from": date_from.isoformat(),
        "param_date_to": date_to.isoformat(),
    }

    # Проверяем все дни диапазона, а не только максимальную дату.
    readiness = query_clickhouse(
        """
        SELECT uniqExact(report_date) AS ready_days
        FROM reports.user_report_cdc_daily
        WHERE report_date BETWEEN
            {date_from:Date} AND {date_to:Date}
        AND is_ready_marker = 1
        """,
        parameters,
    )

    expected_days = (date_to - date_from).days + 1
    ready_days = int(readiness[0]["ready_days"])

    if ready_days != expected_days:
        raise HTTPException(
            status_code=409,
            detail=(
                "Airflow ещё не подготовил весь запрошенный период. "
                "Выберите обработанный период или повторите запрос позже."
            ),
        )

    # Читаем готовую витрину без объединения исходных данных.
    rows = query_clickhouse(
        """
        SELECT
            report_date,
            client_id,
            client_name,
            prosthesis_id,
            signals_count,
            movements_count
        FROM reports.user_report_cdc_daily
        WHERE user_id = {user_id:String}
        AND is_ready_marker = 0
        AND report_date BETWEEN
            {date_from:Date} AND {date_to:Date}
        ORDER BY report_date, prosthesis_id
        """,
        parameters,
    )

    # ClickHouse передаёт UInt64 в JSON строками.
    for row in rows:
        row["signals_count"] = int(row["signals_count"])
        row["movements_count"] = int(row["movements_count"])

    report = {
        "user_id": user_id,
        "date_from": date_from.isoformat(),
        "date_to": date_to.isoformat(),
        "reports": rows,
    }

    key = save_report(report, key=key)

    return {
        "report_url": report_url(key),
    }