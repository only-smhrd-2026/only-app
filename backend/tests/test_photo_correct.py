"""사진 활동 정정·재요청·문제 선택 반영과 접근 범위를 확인한다."""

from datetime import timedelta
from decimal import Decimal

import pytest

from app.ai import quiz
from app.config import now_kst
from app.db import SessionLocal
from app.models import Photo
from app.routers import photos
from tests.conftest import add_photos, make_room, signup


@pytest.fixture
def context(client):
    signup(client)
    room_id = make_room(client)["room_id"]
    photo_id = add_photos(room_id, 1)[0]
    return room_id, photo_id, f"/api/rooms/{room_id}/photos/{photo_id}/correction"


def test_correct_repeat_and_change(client, context, monkeypatch):
    _, photo_id, path = context
    first_time = now_kst()
    monkeypatch.setattr(photos, "now_kst", lambda: first_time)
    with SessionLocal() as db:
        photo = db.get(Photo, photo_id)
        photo.activity = "김장"
        photo.category = "음식"
        photo.confidence = Decimal("0.90")
        photo.analyzed_at = first_time - timedelta(days=1)
        db.commit()
    response = client.patch(path, json={"corrected_activity": "  장 담그기  "})
    assert response.status_code == 200, response.text
    assert response.json()["photo_id"] == photo_id
    assert set(response.json()) == {
        "photo_id",
        "url",
        "taken_at",
        "caption",
        "people_note",
        "status",
        # AI 분류·가족이 고친 활동 (D73 가족방 탭 '올린 사진')
        "source",
        "analyzed",
        "ai_activity",
        "ai_scene",
        "corrected_activity",
    }
    with SessionLocal() as db:
        photo = db.get(Photo, photo_id)
        assert photo.corrected_activity == "장 담그기"
        assert photo.corrected_at == first_time
        assert quiz.photo_tags(photo)[0] == "장 담그기"
        assert photo.activity == "김장"
        assert photo.category == "음식"
        assert photo.confidence == Decimal("0.90")
        assert photo.analyzed_at == first_time - timedelta(days=1)
    later = first_time + timedelta(minutes=1)
    monkeypatch.setattr(photos, "now_kst", lambda: later)
    assert client.patch(path, json={"corrected_activity": "장 담그기"}).status_code == 200
    with SessionLocal() as db:
        assert db.get(Photo, photo_id).corrected_at == first_time
    assert client.patch(path, json={"corrected_activity": "김장"}).status_code == 200
    with SessionLocal() as db:
        photo = db.get(Photo, photo_id)
        assert photo.corrected_activity == "김장"
        assert photo.corrected_at == later
    assert client.patch(path, json={"corrected_activity": "none"}).status_code == 200
    with SessionLocal() as db:
        photo = db.get(Photo, photo_id)
        assert photo.corrected_activity == "none"
        assert quiz.photo_tags(photo)[0] is None


def test_missing_other_room_and_deleted(client, context):
    room_id, photo_id, path = context
    other_room = make_room(client)["room_id"]
    other_photo = add_photos(other_room, 1)[0]
    for hidden in (999999, other_photo):
        response = client.patch(
            f"/api/rooms/{room_id}/photos/{hidden}/correction", json={"corrected_activity": "장 담그기"}
        )
        assert response.status_code == 404
        assert response.json()["code"] == "PHOTO_NOT_FOUND"
    with SessionLocal() as db:
        db.get(Photo, photo_id).status = "DELETED"
        db.commit()
    response = client.patch(path, json={"corrected_activity": "장 담그기"})
    assert response.status_code == 404
    assert response.json()["code"] == "PHOTO_NOT_FOUND"
    with SessionLocal() as db:
        assert db.get(Photo, photo_id).corrected_activity is None
        assert db.get(Photo, other_photo).corrected_activity is None


def test_login_and_membership(client, context):
    _, photo_id, path = context
    signup(client)
    response = client.patch(path, json={"corrected_activity": "장 담그기"})
    assert response.status_code == 404
    assert response.json()["code"] == "ROOM_NOT_FOUND"
    client.cookies.clear()
    response = client.patch(path, json={"corrected_activity": "장 담그기"})
    assert response.status_code == 401
    assert response.json()["code"] == "AUTH_REQUIRED"
    with SessionLocal() as db:
        assert db.get(Photo, photo_id).corrected_activity is None


@pytest.mark.parametrize("value", ["가" * 21, "   ", "\t\n"])
def test_invalid_activity(client, context, value):
    _, photo_id, path = context
    response = client.patch(path, json={"corrected_activity": value})
    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION"
    with SessionLocal() as db:
        photo = db.get(Photo, photo_id)
        assert photo.corrected_activity is None
        assert photo.corrected_at is None
