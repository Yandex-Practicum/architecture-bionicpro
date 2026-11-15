import base64
import hashlib
import hmac
import json
import logging
import os
import re
import time
from datetime import date, datetime
from functools import lru_cache
from threading import Lock
from typing import Annotated
from uuid import UUID

import clickhouse_connect
import boto3
import jwt
from botocore.exceptions import ClientError
from fastapi import Depends, FastAPI, Header, HTTPException, status
from jwt import PyJWKClient
from pydantic import BaseModel


log = logging.getLogger(__name__)
app = FastAPI(title="BionicPRO Reports API")


class Report(BaseModel):
    report_date: date
    prosthesis_id: UUID
    serial_number: str
    model: str
    telemetry_events: int
    movements: int
    avg_response_time_ms: float
    p95_response_time_ms: float
    avg_battery_level_pct: float
    min_battery_level_pct: float
    avg_signal_quality: float
    last_event_at: datetime


class ReportLink(BaseModel):
    url: str
    cached: bool


report_locks = [Lock() for _ in range(64)]


@lru_cache
def jwks_client():
    return PyJWKClient(os.environ["KEYCLOAK_JWKS_URL"])


@lru_cache
def clickhouse_client():
    return clickhouse_connect.get_client(
        host=os.environ["CLICKHOUSE_HOST"],
        port=int(os.getenv("CLICKHOUSE_PORT", "8443")),
        username=os.environ["CLICKHOUSE_USER"],
        password=os.environ["CLICKHOUSE_PASSWORD"],
        secure=os.getenv("CLICKHOUSE_SECURE", "true").lower() == "true",
        database="reporting",
        autogenerate_session_id=False,
    )


@lru_cache
def s3_client():
    client = boto3.client(
        "s3",
        endpoint_url=os.environ["S3_ENDPOINT"],
        aws_access_key_id=os.environ["S3_ACCESS_KEY"],
        aws_secret_access_key=os.environ["S3_SECRET_KEY"],
        region_name="us-east-1",
    )
    bucket = os.getenv("S3_BUCKET", "reports-cache")
    try:
        client.head_bucket(Bucket=bucket)
    except ClientError as error:
        if error.response["Error"]["Code"] not in {"NoSuchBucket", "404"}:
            raise
        client.create_bucket(Bucket=bucket)
        client.put_bucket_policy(
            Bucket=bucket,
            Policy=json.dumps({
                "Version": "2012-10-17",
                "Statement": [{
                    "Effect": "Allow",
                    "Principal": "*",
                    "Action": "s3:GetObject",
                    "Resource": f"arn:aws:s3:::{bucket}/reports/*",
                }],
            }),
        )
        client.put_bucket_lifecycle_configuration(
            Bucket=bucket,
            LifecycleConfiguration={"Rules": [{
                "ID": "expire-report-cache",
                "Status": "Enabled",
                "Filter": {"Prefix": "reports/"},
                "Expiration": {"Days": 7},
            }]},
        )
    return client


def current_user(authorization: Annotated[str | None, Header()] = None) -> UUID:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "missing bearer token")
    token = authorization.removeprefix("Bearer ")
    try:
        key = jwks_client().get_signing_key_from_jwt(token).key
        claims = jwt.decode(
            token,
            key,
            algorithms=["RS256"],
            audience="reports-api",
            issuer=os.environ["KEYCLOAK_ISSUER"],
            options={"require": ["exp", "sub"]},
        )
        if "prothetic_user" not in claims.get("realm_access", {}).get("roles", []):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "report access denied")
        return UUID(claims["sub"])
    except (jwt.PyJWTError, KeyError, ValueError) as error:
        log.warning("Access token rejected: %s", error)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid bearer token")


def get_clickhouse():
    return clickhouse_client()


def get_s3():
    return s3_client()


def cache_version(client, bucket):
    try:
        body = client.get_object(Bucket=bucket, Key="cache-control/current-version")["Body"]
        return body.read().decode()
    except ClientError as error:
        if error.response["Error"]["Code"] in {"NoSuchKey", "404"}:
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "report cache is not ready")
        raise


def crm_cache_version(client):
    result = client.query(
        """
        SELECT
            coalesce(max(crm_clients_version), 0),
            coalesce(max(crm_prostheses_version), 0)
        FROM reporting.user_prosthesis_daily_cdc
        """
    )
    return "-".join(str(value) for value in result.result_rows[0])


def report_key(version, user_id):
    digest = hmac.new(
        os.environ["REPORT_CACHE_KEY"].encode(),
        f"{version}:{user_id}".encode(),
        hashlib.sha256,
    ).hexdigest()
    return f"reports/{version}/{digest}.json"


def cdn_url(key):
    path = f"/{key}"
    expires = int(time.time()) + 300
    digest = hashlib.md5(
        f"{expires}{path} {os.environ['CDN_SIGNING_KEY']}".encode(),
        usedforsecurity=False,
    ).digest()
    signature = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
    return (
        f"{os.environ['CDN_BASE_URL'].rstrip('/')}{path}"
        f"?signature={signature}&expires={expires}"
    )


def object_exists(client, bucket, key):
    try:
        client.head_object(Bucket=bucket, Key=key)
        return True
    except ClientError as error:
        if error.response["Error"]["Code"] in {"NoSuchKey", "404"}:
            return False
        raise


@app.get("/reports", response_model=ReportLink)
def reports(
    user_id: Annotated[UUID, Depends(current_user)],
    client=Depends(get_clickhouse),
    s3=Depends(get_s3),
):
    bucket = os.getenv("S3_BUCKET", "reports-cache")
    try:
        version = f"{cache_version(s3, bucket)}-{crm_cache_version(client)}"
        key = report_key(version, user_id)
        url = cdn_url(key)
        if object_exists(s3, bucket, key):
            return ReportLink(url=url, cached=True)

        with report_locks[hash(key) % len(report_locks)]:
            if object_exists(s3, bucket, key):
                return ReportLink(url=url, cached=True)
            result = client.query(
                """
                SELECT report_date, prosthesis_id, serial_number, model,
                       telemetry_events, movements, avg_response_time_ms,
                       p95_response_time_ms, avg_battery_level_pct,
                       min_battery_level_pct, avg_signal_quality, last_event_at
                FROM reporting.user_prosthesis_daily_cdc
                WHERE user_id = {user_id:UUID} AND is_metadata = 0
                ORDER BY report_date, prosthesis_id
                """,
                parameters={"user_id": str(user_id)},
            )
            reports = [
                Report(**dict(zip(result.column_names, row)))
                for row in result.result_rows
            ]
            s3.put_object(
                Bucket=bucket,
                Key=key,
                Body=json.dumps(
                    [report.model_dump(mode="json") for report in reports]
                ).encode(),
                ContentType="application/json",
            )
            return ReportLink(url=url, cached=False)
    except HTTPException:
        raise
    except Exception:
        log.exception("Report generation failed")
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "reports unavailable")


@app.post("/internal/cache/versions/{version}", status_code=status.HTTP_204_NO_CONTENT)
def publish_cache_version(
    version: str,
    internal_token: Annotated[str | None, Header(alias="X-Internal-Token")] = None,
    s3=Depends(get_s3),
):
    if not internal_token or not hmac.compare_digest(
        internal_token, os.environ["INTERNAL_CACHE_TOKEN"]
    ):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "unauthorized")
    if not re.fullmatch(r"[a-f0-9]{16}", version):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "invalid cache version")
    s3.put_object(
        Bucket=os.getenv("S3_BUCKET", "reports-cache"),
        Key="cache-control/current-version",
        Body=version.encode(),
        ContentType="text/plain",
    )
