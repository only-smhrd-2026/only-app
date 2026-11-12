"""어르신 카메라 업로드: 기기 확인·연결 반환·재전송·사진 일기 연결 (D17)."""

import io
import uuid

import pytest
from PIL import Image
from sqlalchemy import func, select
from starlette import formparsers

from app.config import UPLOAD_MAX_BYTES
from app.db import SessionLocal, engine
from app.models import Photo
from app.routers import elder as elder_api
from tests.conftest import setup_elder, signup


def _jpeg() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (40, 30), "red").save(buf, "JPEG")
    return buf.getvalue()


def _upload(client, content=None, **kwargs):
    return client.post(
        "/api/elder/photos",
        files=[("files", ("c.jpg", _jpeg() if content is None else content, "image/jpeg"))],
        **kwargs,
    )


def test_upload_album_media_and_diary(client):
    setup_elder(client)
    r = _upload(client)
    assert r.status_code == 201, r.text
    photo = r.json()
    with SessionLocal() as db:
        stored = db.get(Photo, photo["photo_id"])
        assert stored.source == "ELDER_CAMERA" and stored.uploaded_by is None
    assert client.get("/api/elder/album").json()["photos"][0]["photo_id"] == photo["photo_id"]
    media = client.get(photo["url"])
    assert media.status_code == 200 and media.headers["content-type"] == "image/jpeg"
    r = client.post(
        "/api/elder/sessions",
        json={"session_id": str(uuid.uuid4()), "kind": "DIARY", "photo_id": photo["photo_id"]},
    )
    assert r.status_code == 201, r.text
    assert r.json()["photo_url"] == photo["url"]


def test_device_checked_before_body(client, monkeypatch):
    parsed, original = [], formparsers.MultiPartParser.parse

    async def spy(self):
        parsed.append(1)
        return await original(self)

    monkeypatch.setattr(formparsers.MultiPartParser, "parse", spy)
    signup(client)
    r = _upload(client)
    assert r.status_code == 401 and r.json()["code"] == "DEVICE_REQUIRED"
    assert parsed == []


def test_waiting_for_lock_holds_no_db_connection(client, monkeypatch):
    setup_elder(client)
    seen = []

    class SpyLock:
        def acquire(self, timeout):
            seen.append(engine.pool.checkedout())
            return True

        def release(self):
            pass

    monkeypatch.setattr(elder_api, "_upload_lock", SpyLock())
    assert _upload(client).status_code == 201
    assert seen == [0]


def test_bad_image_and_too_many_photos(client):
    setup_elder(client)
    r = _upload(client, b"not an image")
    assert r.status_code == 400 and r.json()["code"] == "BAD_IMAGE"
    r = client.post("/api/elder/photos", files=[("files", ("c.jpg", _jpeg(), "image/jpeg"))] * 2)
    assert r.status_code == 400 and r.json()["code"] == "TOO_MANY_PHOTOS"


def test_same_batch_saved_once(client):
    ctx = setup_elder(client)
    batch = {"upload_batch_id": str(uuid.uuid4())}
    first, second = _upload(client, data=batch), _upload(client, data=batch)
    assert first.status_code == second.status_code == 201
    assert first.json()["photo_id"] == second.json()["photo_id"]
    with SessionLocal() as db:
        assert (
            db.scalar(
                select(func.count())
                .select_from(Photo)
                .where(Photo.room_id == ctx["room_id"], Photo.source == "ELDER_CAMERA")
            )
            == 1
        )


@pytest.mark.parametrize("batch,status", [("", 201), ("bad", 422)])
def test_batch_validation(client, batch, status):
    setup_elder(client)
    assert _upload(client, data={"upload_batch_id": batch}).status_code == status


def test_missing_and_oversized_photo(client):
    setup_elder(client)
    r = client.post("/api/elder/photos", data={"upload_batch_id": ""})
    assert r.status_code == 422 and r.json()["code"] == "VALIDATION"
    r = _upload(client, b"x" * (UPLOAD_MAX_BYTES + 1))
    assert r.status_code == 400 and r.json()["code"] == "PHOTO_TOO_BIG"
