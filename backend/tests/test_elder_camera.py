"""어르신 카메라 업로드: 기기 확인·연결 반환·재전송·사진 일기 연결 (D17)."""

import io
import uuid
from datetime import timedelta

import pytest
from PIL import Image
from sqlalchemy import delete, func, select
from starlette import formparsers

from app.config import UPLOAD_MAX_BYTES, now_kst
from app.db import SessionLocal, engine
from app.models import DailyPick, Photo
from app.routers import elder as elder_api
from app.routers import photos as photo_api
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


def test_upload_media_and_diary_but_not_in_album(client):
    setup_elder(client)
    r = _upload(client)
    assert r.status_code == 201, r.text
    photo = r.json()
    with SessionLocal() as db:
        stored = db.get(Photo, photo["photo_id"])
        assert stored.source == "ELDER_CAMERA" and stored.uploaded_by is None
    # 일기에 찍은 사진은 사진첩에 넣지 않는다 — 지난 일기에서 일기와 함께 본다 (D60)
    assert photo["photo_id"] not in [p["photo_id"] for p in client.get("/api/elder/album").json()["photos"]]
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


def test_camera_shares_upload_lock_and_503_when_busy(client, monkeypatch):
    """카메라 사진도 가족 업로드와 같은 잠금을 쓴다 — 변환은 서버 전체에서 한 번에 하나(D17). 기다려도 안 풀리면 503."""
    setup_elder(client)
    assert elder_api._upload_lock is photo_api._upload_lock
    monkeypatch.setattr(elder_api, "UPLOAD_LOCK_WAIT_SEC", 0.1)
    with photo_api._upload_lock:  # 가족이 사진을 올리는 중
        r = _upload(client)
    assert r.status_code == 503 and r.json()["code"] == "UPLOAD_BUSY"
    assert _upload(client).status_code == 201  # 잠금이 풀리면 다시 된다


def test_camera_photo_is_never_todays_pick(client):
    """오늘의 한 장 후보는 가족이 올린 사진만 — 카메라 사진은 며칠 전 것이어도 뽑히지 않는다 (services/picks.py)."""
    ctx = setup_elder(client)
    photo_id = _upload(client).json()["photo_id"]
    with SessionLocal() as db:
        db.get(Photo, photo_id).uploaded_at = now_kst() - timedelta(days=2)
        for p in db.scalars(select(Photo).where(Photo.room_id == ctx["room_id"], Photo.source == "FAMILY")):
            p.usable = False  # 가족 사진을 전부 못 쓰게 해서, 남는 후보가 카메라 사진뿐이어도
        db.execute(delete(DailyPick).where(DailyPick.room_id == ctx["room_id"]))
        db.commit()
    assert client.get("/api/elder/home").json()["today_pick"] is None


def test_same_batch_in_another_room_is_a_new_photo(client):
    """같은 요청 번호여도 다른 가족방이면 새 사진 — 남의 방 사진 정보를 돌려주지 않는다."""
    first_room = setup_elder(client)["room_id"]
    batch = {"upload_batch_id": str(uuid.uuid4())}
    first = _upload(client, data=batch).json()
    second_room = setup_elder(client)["room_id"]  # 새 가족·새 방·새 기기 (쿠키가 바뀐다)
    second = _upload(client, data=batch).json()
    assert second_room != first_room and second["photo_id"] != first["photo_id"]
    assert f"/rooms/{second_room}/" in second["url"]
