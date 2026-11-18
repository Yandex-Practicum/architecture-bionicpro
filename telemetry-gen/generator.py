import os, random, time, uuid
import psycopg2

DEVICES = [
    "d67d279a-b64a-4646-8ea6-4a562fbb960e",  # prothetic1
    "4d070f89-5fd1-4853-a7cf-66be63f27217",  # prothetic2
]
EVENTS = ["grip", "release", "mode_switch"]
MODES = ["power", "precision", "auto"]

for attempt in range(30):
    try:
        conn = psycopg2.connect(os.environ["TELEMETRY_DB_CONN"])
        break
    except psycopg2.OperationalError:
        print(f"БД недоступна, попытка {attempt + 1}/30", flush=True)
        time.sleep(2)
else:
    raise SystemExit("Не удалось подключиться к telemetry-db")
conn.autocommit = True

print("Генератор телеметрии запущен", flush=True)
while True:
    with conn.cursor() as cur:
        for _ in range(random.randint(1, 5)):
            cur.execute(
                "INSERT INTO telemetry_events (event_id, device_id, ts, event_type, mode, duration_seconds)"
                " VALUES (%s, %s, now(), %s, %s, %s) ON CONFLICT (event_id) DO NOTHING",
                (str(uuid.uuid4()), random.choice(DEVICES), random.choice(EVENTS),
                 random.choice(MODES), random.randint(20, 300)),
            )

        if random.random() < 0.05:
            for _ in range(random.randint(30, 80)):
                cur.execute(
                    "INSERT INTO telemetry_events (event_id, device_id, ts, event_type, mode, duration_seconds)"
                    " VALUES (%s, %s, now() - (%s || ' seconds')::interval, %s, %s, %s)"
                    " ON CONFLICT (event_id) DO NOTHING",
                    (str(uuid.uuid4()), random.choice(DEVICES), random.randint(60, 6 * 3600),
                     random.choice(EVENTS), random.choice(MODES), random.randint(20, 300)),
                )
            print("Отправлен пакет событий после оффлайна", flush=True)
    time.sleep(10)