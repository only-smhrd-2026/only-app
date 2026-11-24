"""사진 한 장마다 설명 고치기 (D98) — PATCH /rooms/{id}/photos/{photo_id}. 올린 사람이나 방장만, 보낸 칸만 바꾼다."""

from datetime import date

import pytest

from app.config import today_kst
from app.db import SessionLocal
from app.models import Photo
from tests.conftest import make_room, signup
from tests.test_photo_delete import upload
from tests.test_photos import _jpeg
from tests.test_room_members import join, login


def _patch(client, room_id, photo_id, **body):
    return client.patch(f"/api/rooms/{room_id}/photos/{photo_id}", json=body)


def test_uploader_changes_one_photo_only_sent_fields(client):
    signup(client)
    room_id = make_room(client)["room_id"]
    first = client.post(
        f"/api/rooms/{room_id}/photos",
        files=[("files", (f"{i}.jpg", _jpeg(), "image/jpeg")) for i in range(2)],
        data={"caption": "가족 여행", "people_note": "엄마"},
    ).json()["photos"]
    pid, other = first[0]["photo_id"], first[1]["photo_id"]
    r = _patch(client, room_id, pid, caption="  제주 바다  ", taken_year=1988)
    assert r.status_code == 200, r.text
    assert (r.json()["caption"], r.json()["people_note"], r.json()["taken_year"]) == ("제주 바다", "엄마", 1988)
    r = _patch(client, room_id, pid, people_note=None)  # null 은 지운다, 안 보낸 칸은 그대로
    assert (r.json()["caption"], r.json()["people_note"], r.json()["taken_year"]) == ("제주 바다", None, 1988)
    assert _patch(client, room_id, pid, caption="").json()["caption"] is None  # 빈 글도 지운다
    with SessionLocal() as db:  # 같은 묶음의 다른 사진은 그대로
        assert (db.get(Photo, other).caption, db.get(Photo, other).people_note) == ("가족 여행", "엄마")


BAD = [{"caption": "가" * 101}, {"people_note": "a\x00b"}, {"taken_year": 1899}, {"taken_year": today_kst().year + 1}]


@pytest.mark.parametrize("body", BAD)
def test_same_checks_as_upload(client, body):
    signup(client)
    room_id = make_room(client)["room_id"]
    pid = upload(client, room_id)["photo_id"]
    r = _patch(client, room_id, pid, **body)
    assert (r.status_code, r.json()["code"]) == (422, "VALIDATION")


def test_year_is_only_for_photos_without_taken_date(client):
    signup(client)
    room_id = make_room(client)["room_id"]
    pid = upload(client, room_id)["photo_id"]
    with SessionLocal() as db:
        db.get(Photo, pid).taken_at = date(2001, 5, 5)
        db.commit()
    assert _patch(client, room_id, pid, taken_year=1990).json()["taken_year"] is None  # 폰이 적은 날짜가 먼저


def test_only_uploader_or_owner(client):
    owner = signup(client)
    room_id = make_room(client)["room_id"]
    owners = upload(client, room_id)["photo_id"]
    join(client, room_id)  # 손주로 로그인
    mine = upload(client, room_id)["photo_id"]
    r = _patch(client, room_id, owners, caption="몰래")
    assert (r.status_code, r.json()["code"]) == (403, "NOT_UPLOADER")
    assert _patch(client, room_id, mine, caption="내 사진").status_code == 200
    login(client, owner)
    assert _patch(client, room_id, mine, caption="방장이 고침").json()["caption"] == "방장이 고침"

    assert client.delete(f"/api/rooms/{room_id}/photos/{mine}").status_code == 204
    assert _patch(client, room_id, mine, caption="x").json()["code"] == "PHOTO_NOT_FOUND"  # 지운 사진
    signup(client)  # 다른 가족 — 남의 방 사진
    other_room = make_room(client)["room_id"]
    assert _patch(client, room_id, owners, caption="x").status_code == 404
    assert _patch(client, other_room, owners, caption="x").json()["code"] == "PHOTO_NOT_FOUND"
    with SessionLocal() as db:
        assert db.get(Photo, owners).caption is None  # 막힌 요청은 아무것도 안 바꿨다


def test_diary_photo_is_not_edited_here(client):
    signup(client)
    room_id = make_room(client)["room_id"]
    pid = upload(client, room_id, source="FAMILY_DIARY")["photo_id"]
    r = _patch(client, room_id, pid, caption="x")
    assert (r.status_code, r.json()["code"]) == (400, "DIARY_PHOTO")
