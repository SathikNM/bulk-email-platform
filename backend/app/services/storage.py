"""Object storage for import files and email images: local volume or S3-compatible."""
import os
import uuid
from pathlib import Path

from app.core.config import settings


def _s3():
    import boto3
    return boto3.client(
        "s3", endpoint_url=settings.S3_ENDPOINT_URL, region_name=settings.AWS_REGION,
        aws_access_key_id=settings.AWS_ACCESS_KEY_ID or "any",
        aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY or "any",
    )


def new_key(workspace_id: uuid.UUID, folder: str, filename: str) -> str:
    safe = "".join(c for c in os.path.basename(filename) if c.isalnum() or c in "._-") or "file"
    return f"{workspace_id}/{folder}/{uuid.uuid4().hex}_{safe[-80:]}"


def put(key: str, data: bytes, content_type: str = "application/octet-stream") -> None:
    if settings.STORAGE_BACKEND == "s3":
        client = _s3()
        try:
            client.head_bucket(Bucket=settings.S3_BUCKET)
        except Exception:  # noqa: BLE001
            client.create_bucket(Bucket=settings.S3_BUCKET)
        client.put_object(Bucket=settings.S3_BUCKET, Key=key, Body=data, ContentType=content_type)
        return
    path = Path(settings.LOCAL_STORAGE_DIR) / key
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def get(key: str) -> bytes:
    if settings.STORAGE_BACKEND == "s3":
        return _s3().get_object(Bucket=settings.S3_BUCKET, Key=key)["Body"].read()
    return (Path(settings.LOCAL_STORAGE_DIR) / key).read_bytes()


def public_url(key: str) -> str:
    if settings.STORAGE_BACKEND == "s3" and settings.S3_PUBLIC_BASE_URL:
        return f"{settings.S3_PUBLIC_BASE_URL.rstrip('/')}/{key}"
    return f"{settings.PUBLIC_BASE_URL.rstrip('/')}/assets/{key}"
