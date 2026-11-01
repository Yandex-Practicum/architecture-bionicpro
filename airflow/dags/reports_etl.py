import json
import os
from datetime import date
from pathlib import Path
from urllib.parse import urlparse

import psycopg2
import requests


class ClickHouse:
    def __init__(self):
        self.url = os.environ.get(
            "CLICKHOUSE_URL",
            "http://clickhouse:8123",
        )
        self.http = requests.Session()
        self.http.auth = (
            os.environ.get("CLICKHOUSE_USER", "reports"),
            os.environ["CLICKHOUSE_PASSWORD"],
        )

    def execute(self, sql, rows=None):
        payload = sql

        if rows is not None:
            payload += "\n" + "\n".join(
                json.dumps(row, ensure_ascii=False)
                for row in rows
            )

        try:
            response = self.http.post(
                self.url,
                data=payload.encode("utf-8"),
                timeout=60,
            )
            response.raise_for_status()
        except requests.RequestException:
            raise RuntimeError(
                "ClickHouse request failed; see server logs"
            ) from None

        return response.text.strip()

    def close(self):
        self.http.close()


def initialize():
    """Создаёт таблицы ClickHouse, если они ещё не существуют."""
    ch = ClickHouse()

    try:
        sql = Path(
            "/opt/airflow/sql/clickhouse.sql"
        ).read_text(encoding="utf-8")

        for statement in sql.split(";"):
            if statement.strip():
                ch.execute(statement)
    finally:
        ch.close()


def bitrix_contacts():
    """Читает контакты Bitrix24 с постраничной загрузкой."""
    base = os.environ.get("CRM_WEBHOOK_URL", "")

    if urlparse(base).scheme != "https":
        raise ValueError(
            "CRM_WEBHOOK_URL must be a configured HTTPS webhook base URL"
        )

    user_field = os.environ.get(
        "CRM_USER_ID_FIELD",
        "UF_CRM_KEYCLOAK_SUB",
    )
    device_field = os.environ.get(
        "CRM_PROSTHESIS_IDS_FIELD",
        "UF_CRM_PROSTHESIS_IDS",
    )

    start = 0
    seen = set()

    with requests.Session() as http:
        while True:
            if start in seen:
                raise ValueError(
                    "CRM pagination repeated a page"
                )

            seen.add(start)

            try:
                response = http.post(
                    base.rstrip("/") + "/crm.contact.list.json",
                    data={
                        "select[]": [
                            "ID",
                            user_field,
                            device_field,
                        ],
                        "start": start,
                    },
                    timeout=30,
                )
                response.raise_for_status()
                page = response.json()
            except (requests.RequestException, ValueError):
                # URL вебхука содержит секрет, поэтому не выводим его.
                raise RuntimeError(
                    "CRM request failed; check the local webhook configuration"
                ) from None

            if (
                page.get("error")
                or not isinstance(page.get("result"), list)
            ):
                raise ValueError(
                    "CRM did not return a contact list"
                )

            yield from page["result"]

            if "next" not in page:
                break

            start = int(page["next"])


def crm_contacts():
    """Выбирает источник CRM: учебный JSON или Bitrix24."""
    mode = os.environ.get("CRM_SOURCE", "fixture")

    if mode == "bitrix24":
        yield from bitrix_contacts()

    elif mode == "fixture":
        path = Path(
            os.environ.get(
                "CRM_FIXTURE_PATH",
                "/opt/airflow/fixtures/crm.json",
            )
        )
        data = json.loads(
            path.read_text(encoding="utf-8")
        )

        if not isinstance(data.get("result"), list):
            raise ValueError("Invalid CRM fixture")

        yield from data["result"]

    else:
        raise ValueError(
            "CRM_SOURCE must be fixture or bitrix24"
        )


def normalize_clients(contacts):
    """Преобразует контакты в отдельные связи клиент — протез."""
    user_field = os.environ.get(
        "CRM_USER_ID_FIELD",
        "UF_CRM_KEYCLOAK_SUB",
    )
    device_field = os.environ.get(
        "CRM_PROSTHESIS_IDS_FIELD",
        "UF_CRM_PROSTHESIS_IDS",
    )

    owners = set()

    for contact in contacts:
        devices = contact.get(device_field) or []

        if isinstance(devices, str):
            devices = [devices]

        if not isinstance(devices, list):
            raise ValueError(
                "CRM prosthesis IDs must be a list or a string"
            )

        if not devices:
            continue

        user_id = str(
            contact.get(user_field) or ""
        ).strip()

        client_id = str(
            contact.get("ID") or ""
        ).strip()

        if not user_id or not client_id:
            raise ValueError(
                "A prosthesis owner is missing user_id or client_id"
            )

        for value in devices:
            device = str(value).strip()

            if not device or device in owners:
                raise ValueError(
                    "Empty or ambiguous prosthesis ownership in CRM"
                )

            owners.add(device)

            yield {
                "client_id": client_id,
                "user_id": user_id,
                "prosthesis_id": device,
            }


def load_crm():
    """Загружает связи клиентов и протезов в ClickHouse."""
    ch = ClickHouse()

    try:
        ch.execute("TRUNCATE TABLE reports.crm_stage")

        batch = []

        for row in normalize_clients(crm_contacts()):
            batch.append(row)

            if len(batch) == 1000:
                ch.execute(
                    "INSERT INTO reports.crm_stage FORMAT JSONEachRow",
                    batch,
                )
                batch = []

        if batch:
            ch.execute(
                "INSERT INTO reports.crm_stage FORMAT JSONEachRow",
                batch,
            )
    finally:
        ch.close()


def load_telemetry(start, end):
    """Загружает телеметрию за интервал [start, end)."""
    ch = ClickHouse()

    try:
        ch.execute(
            "TRUNCATE TABLE reports.telemetry_stage"
        )

        try:
            with psycopg2.connect(
                os.environ["TELEMETRY_DSN"]
            ) as connection:
                with connection.cursor(
                    name="daily_telemetry"
                ) as cursor:
                    cursor.execute(
                        """
                        SELECT
                            event_id,
                            prosthesis_id,
                            occurred_at,
                            event_type
                        FROM telemetry_events
                        WHERE occurred_at >= %s
                          AND occurred_at < %s
                        """,
                        (start, end),
                    )

                    while True:
                        batch = cursor.fetchmany(1000)

                        if not batch:
                            break

                        rows = [
                            {
                                "event_id": event_id,
                                "prosthesis_id": device,
                                "occurred_at": occurred.isoformat(),
                                "event_type": kind,
                            }
                            for event_id, device, occurred, kind
                            in batch
                        ]

                        ch.execute(
                            """
                            INSERT INTO reports.telemetry_stage
                            SETTINGS date_time_input_format='best_effort'
                            FORMAT JSONEachRow
                            """,
                            rows,
                        )

        except psycopg2.Error:
            raise RuntimeError(
                "Telemetry extraction failed; check the PostgreSQL source"
            ) from None
    finally:
        ch.close()


def publish(report_date):
    """Объединяет источники и публикует готовую дневную витрину."""
    day = date.fromisoformat(report_date).isoformat()
    ch = ClickHouse()

    try:
        missing = ch.execute(
            """
            SELECT count()
            FROM reports.telemetry_stage t
            LEFT ANTI JOIN reports.crm_current_prostheses c
                ON t.prosthesis_id = c.prosthesis_id
            """
        )

        if int(missing):
            raise ValueError(
                "Telemetry has prostheses without a CRM owner; "
                "period is not ready"
            )

        ch.execute(
            "TRUNCATE TABLE reports.report_daily_stage"
        )

        ch.execute(
            f"""
            INSERT INTO reports.report_daily_stage
            SELECT
                toDate('{day}'),
                c.user_id,
                c.client_id,
                t.prosthesis_id,
                countIf(t.event_type = 'signal'),
                countIf(t.event_type = 'movement')
            FROM reports.telemetry_stage t
            INNER JOIN reports.crm_current_prostheses c
                ON t.prosthesis_id = c.prosthesis_id
            GROUP BY
                c.user_id,
                c.client_id,
                t.prosthesis_id
            """
        )

        count = int(
            ch.execute(
                "SELECT count() FROM reports.report_daily_stage"
            )
        )

        if count:
            # Заменяем день целиком: повторный запуск не создаёт дубли.
            ch.execute(
                f"""
                ALTER TABLE reports.user_report_daily
                REPLACE PARTITION '{day}'
                FROM reports.report_daily_stage
                """
            )
        else:
            ch.execute(
                f"""
                ALTER TABLE reports.user_report_daily
                DROP PARTITION '{day}'
                """
            )

        # Готовность фиксируется после успешной публикации,
        # в том числе для дня без событий.
        ch.execute(
            f"""
            INSERT INTO reports.etl_periods
            VALUES ('{day}', 'ready', now64(3))
            """
        )
    finally:
        ch.close()