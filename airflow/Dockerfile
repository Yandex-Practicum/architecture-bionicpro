FROM apache/airflow:2.9.3-python3.11

USER root
COPY start.sh /opt/airflow/start.sh
RUN sed -i 's/\r$//' /opt/airflow/start.sh \
    && chmod 755 /opt/airflow/start.sh \
    && chown airflow:root /opt/airflow/start.sh

USER airflow
RUN pip install --no-cache-dir clickhouse-connect==0.8.6 psycopg2-binary==2.9.10
