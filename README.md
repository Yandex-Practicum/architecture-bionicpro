# BionicPRO

Команда для запуска всей системы:

```shell
export SESSION_ENCRYPTION_KEY=$(openssl rand -base64 32 | tr '+/' '-_' | tr -d '=') \
export YANDEX_CLIENT_ID=<Yandex OAuth application ID> \
export YANDEX_CLIENT_SECRET=<Yandex OAuth application secret> \
export YANDEX_BRIDGE_SECRET=$(openssl rand -hex 32) \
export MINIO_ROOT_USER=minio_user \
export MINIO_ROOT_PASSWORD=$(openssl rand -hex 32) \
export REPORT_CACHE_KEY=$(openssl rand -hex 32) \
export CDN_SIGNING_KEY=$(openssl rand -hex 32) \
export INTERNAL_CACHE_TOKEN=$(openssl rand -hex 32) \
export DEBEZIUM_DB_PASSWORD=$(openssl rand -hex 32)
docker-compose up --build
```

Фронт доступен тут `http://localhost:3000`. Тестовые пользователи перечислены здесь `keycloak/realm-export.json`.

Остальные части системы:

- Airflow UI: `http://localhost:8081`. Логин `admin` / `admin`
- ClickHouse HTTP: `http://localhost:8123`
- Reports API: `http://localhost:8001` (тут нужна аутентификация)
- Reports CDN: `http://localhost:8082`
- CRM PostgreSQL: `localhost:5434`
- telemetry PostgreSQL: `localhost:5435`