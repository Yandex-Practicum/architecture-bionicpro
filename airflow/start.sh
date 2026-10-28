#!/usr/bin/env bash
set -euo pipefail

pip install --no-cache-dir clickhouse-connect==0.8.6 psycopg2-binary==2.9.10

airflow db migrate
airflow users create \
  --username admin \
  --password admin \
  --firstname Admin \
  --lastname User \
  --role Admin \
  --email admin@example.com || true

exec airflow standalone
