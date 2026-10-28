import os
from typing import Optional

import clickhouse_connect
import jwt
from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt import PyJWKClient

app = FastAPI(title="BionicPRO Reports API")
security = HTTPBearer(auto_error=False)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

KEYCLOAK_URL = os.environ.get("KEYCLOAK_URL", "http://localhost:8080")
REALM = os.environ.get("KEYCLOAK_REALM", "reports-realm")
REPORT_ROLE = "prothetic_user"

_jwks_client: Optional[PyJWKClient] = None


def get_jwks_client() -> PyJWKClient:
    global _jwks_client
    if _jwks_client is None:
        url = f"{KEYCLOAK_URL}/realms/{REALM}/protocol/openid-connect/certs"
        _jwks_client = PyJWKClient(url)
    return _jwks_client


def clickhouse_client():
    return clickhouse_connect.get_client(
        host=os.environ.get("CLICKHOUSE_HOST", "localhost"),
        port=int(os.environ.get("CLICKHOUSE_PORT", "8123")),
        username=os.environ.get("CLICKHOUSE_USER", "default"),
        password=os.environ.get("CLICKHOUSE_PASSWORD", ""),
        database=os.environ.get("CLICKHOUSE_DATABASE", "olap"),
    )


def current_user(
    creds: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> str:
    if creds is None or not creds.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )

    token = creds.credentials
    try:
        signing_key = get_jwks_client().get_signing_key_from_jwt(token)
        payload = jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            options={"verify_aud": False},
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid token: {exc}",
        ) from exc

    roles = set(payload.get("realm_access", {}).get("roles", []))
    if REPORT_ROLE not in roles:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Forbidden",
        )

    username = payload.get("preferred_username") or payload.get("sub")
    if not username:
        raise HTTPException(status_code=401, detail="No username in token")
    return username


def empty_report(username: str) -> dict:
    return {
        "user_id": username,
        "full_name": "",
        "email": "",
        "prosthesis_model": "",
        "total_steps": 0,
        "total_distance_m": 0.0,
        "avg_load_kg": 0.0,
        "sessions_count": 0,
        "last_activity_at": None,
        "updated_at": None,
    }


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/reports")
def get_my_report(username: str = Depends(current_user)):
    """Own report from ClickHouse. Empty until the Airflow DAG has loaded the mart."""
    client = clickhouse_client()
    try:
        result = client.query(
            """
            SELECT user_id, full_name, email, prosthesis_model,
                   total_steps, total_distance_m, avg_load_kg,
                   sessions_count, last_activity_at, updated_at
            FROM report_mart
            WHERE user_id = {user_id:String}
            """,
            parameters={"user_id": username},
        )
    finally:
        client.close()

    if not result.result_rows:
        return empty_report(username)

    report = dict(zip(result.column_names, result.result_rows[0]))
    if report["user_id"] != username:
        raise HTTPException(status_code=403, detail="Forbidden")

    for key in ("last_activity_at", "updated_at"):
        if report.get(key) is not None:
            report[key] = report[key].isoformat()
    return report
