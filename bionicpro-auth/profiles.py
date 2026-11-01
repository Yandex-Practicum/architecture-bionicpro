import os
from pathlib import Path
import sqlite3
from datetime import datetime, timezone

PROFILE_DB = Path(os.environ.get('PROFILE_DB', '.local/yandex-profiles.sqlite3'))

def initialize():
    PROFILE_DB.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(PROFILE_DB) as db:
        db.execute('''CREATE TABLE IF NOT EXISTS yandex_profiles (
            subject TEXT PRIMARY KEY, yandex_id TEXT NOT NULL, login TEXT,
            display_name TEXT, email TEXT, consented_at TEXT NOT NULL)''')
    os.chmod(PROFILE_DB, 0o600)

def save(subject, profile):
    external_id = str(profile.get('id') or '')
    if not external_id:
        raise ValueError('Yandex profile has no ID')
    with sqlite3.connect(PROFILE_DB) as db:
        db.execute('''INSERT INTO yandex_profiles VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(subject) DO UPDATE SET yandex_id=excluded.yandex_id,
            login=excluded.login, display_name=excluded.display_name,
            email=excluded.email, consented_at=excluded.consented_at''',
            (subject, external_id, profile.get('login'), profile.get('display_name'),
             profile.get('default_email'), datetime.now(timezone.utc).isoformat()))
