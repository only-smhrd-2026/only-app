"""사진 저장 부품 (초석 F). STORAGE=local 이면 UPLOAD_DIR 폴더(기본 only-app/uploads, git 제외), r2 면 Cloudflare R2.

key 모양은 rooms/{room_id}/{upload_batch_id}/{index}.jpg 로 고정 (D17). 로컬은 경로 탐색 방어 2중 (D18):
정규식 + resolve() 가 base 안인지 확인.
서명 URL 없이 GET /api/media/{key} 가 쿠키로 권한을 확인하고 바이트를 돌려준다 (D2).
"""

from __future__ import annotations

import re
from pathlib import Path

from app.config import settings

KEY_RE = re.compile(r"^rooms/\d+/[0-9a-f-]{36}(/\d+)?\.jpg$")


def valid_key(key: str) -> bool:
    return bool(KEY_RE.match(key))


class _Local:
    def __init__(self) -> None:
        self.base = Path(settings.UPLOAD_DIR).resolve()

    def _path(self, key: str) -> Path:
        p = (self.base / key).resolve()
        if not p.is_relative_to(self.base):
            raise ValueError("잘못된 key")
        return p

    def put(self, key: str, data: bytes, content_type: str = "image/jpeg") -> None:
        p = self._path(key)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)

    def get(self, key: str) -> bytes | None:
        p = self._path(key)
        return p.read_bytes() if p.is_file() else None


class _R2:
    """Cloudflare R2 (S3 호환). R2_* 값이 .env 에 있어야 한다."""

    def __init__(self) -> None:
        import boto3

        self.client = boto3.client(
            "s3",
            endpoint_url=f"https://{settings.R2_ACCOUNT_ID}.r2.cloudflarestorage.com",
            aws_access_key_id=settings.R2_ACCESS_KEY_ID,
            aws_secret_access_key=settings.R2_SECRET_ACCESS_KEY,
            region_name="auto",
        )
        self.bucket = settings.R2_BUCKET

    def put(self, key: str, data: bytes, content_type: str = "image/jpeg") -> None:
        self.client.put_object(Bucket=self.bucket, Key=key, Body=data, ContentType=content_type)

    def get(self, key: str) -> bytes | None:
        try:
            return self.client.get_object(Bucket=self.bucket, Key=key)["Body"].read()
        except self.client.exceptions.NoSuchKey:
            return None


_backend: _Local | _R2 | None = None


def _get_backend() -> _Local | _R2:
    global _backend
    if _backend is None:
        _backend = _R2() if settings.STORAGE == "r2" else _Local()
    return _backend


def put(key: str, data: bytes, content_type: str = "image/jpeg") -> None:
    if not valid_key(key):
        raise ValueError("잘못된 key")
    _get_backend().put(key, data, content_type)


def get(key: str) -> bytes | None:
    if not valid_key(key):
        return None
    return _get_backend().get(key)
