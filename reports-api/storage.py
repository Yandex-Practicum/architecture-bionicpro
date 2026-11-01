import hashlib
import json
import os
import time

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError
from fastapi import HTTPException
from urllib.parse import urlsplit

BUCKET = os.environ.get("S3_BUCKET", "reports")


def get_s3_client():
    return boto3.client(
        "s3",
        endpoint_url=os.environ["S3_ENDPOINT_URL"],
        aws_access_key_id=os.environ["S3_ACCESS_KEY"],
        aws_secret_access_key=os.environ["S3_SECRET_KEY"],
        region_name="us-east-1",
        config=Config(
            signature_version="s3v4",
            s3={"addressing_style": "path"},
            connect_timeout=3,
            read_timeout=10,
            retries={
                "mode": "standard",
                "max_attempts": 2,
            },
        ),
    )


def report_key(user_id, date_from, date_to):
    user_directory = hashlib.sha256(
        user_id.encode("utf-8")
    ).hexdigest()

    version = int(time.time()) // 60

    return (
        f"reports/{user_directory}/"
        f"{date_from}_{date_to}_v{version}_cdc1.json"
    )


def save_report(report, key=None):
    if key is None:
        key = report_key(
            report["user_id"],
            report["date_from"],
            report["date_to"],
        )

    body = json.dumps(
        report,
        ensure_ascii=False,
    ).encode("utf-8")

    try:
        get_s3_client().put_object(
            Bucket=BUCKET,
            Key=key,
            Body=body,
            ContentType="application/json; charset=utf-8",
        )
    except (BotoCoreError, ClientError):
        raise HTTPException(
            status_code=502,
            detail="Не удалось сохранить отчёт в объектное хранилище",
        ) from None

    return key

def report_exists(key):
    try:
        get_s3_client().head_object(
            Bucket=BUCKET,
            Key=key,
        )
        return True

    except ClientError as error:
        code = error.response["Error"]["Code"]

        if code in ("404", "NoSuchKey", "NotFound"):
            return False

        raise HTTPException(
            status_code=502,
            detail="Не удалось проверить наличие отчёта",
        ) from None

    except BotoCoreError:
        raise HTTPException(
            status_code=502,
            detail="Объектное хранилище недоступно",
        ) from None


def report_url(key):
    try:
        signed_url = get_s3_client().generate_presigned_url(
            "get_object",
            Params={
                "Bucket": BUCKET,
                "Key": key,
            },
            ExpiresIn=300,
        )
    except (BotoCoreError, ClientError):
        raise HTTPException(
            status_code=502,
            detail="Не удалось подготовить ссылку на отчёт",
        ) from None

    # Внешняя ссылка ведёт через проверку сессии и CDN.
    query = urlsplit(signed_url).query
    return f"/cdn/{key}?{query}"