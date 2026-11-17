"""게시 시각이 같은 일기도 중복 없이 가족 일기 다음 쪽으로 넘긴다."""

import uuid
from datetime import timedelta

from app.config import now_kst
from app.db import SessionLocal
from app.models import Diary
from tests.conftest import make_room, signup


def test_diary_pages_with_tied_times(client):
    user = signup(client)
    room_id = make_room(client)["room_id"]
    now = now_kst()
    with SessionLocal() as db:
        db.add_all(
            Diary(
                room_id=room_id,
                author_type="FAMILY",
                author_user_id=user["user_id"],
                body=f"소식 {i}",
                mood="GOOD",
                illustration_type="NONE",
                request_id=uuid.uuid4(),
                posted_at=now - timedelta(minutes=i // 7),
            )
            for i in range(55)
        )
        db.commit()
    first = client.get(f"/api/rooms/{room_id}/diaries").json()
    assert len(first["diaries"]) == 50 and first["has_more"] is True
    cursor = first["diaries"][-1]["diary_id"]
    second = client.get(f"/api/rooms/{room_id}/diaries?before={cursor}").json()
    assert len(second["diaries"]) == 5 and second["has_more"] is False
    assert not {d["diary_id"] for d in first["diaries"]} & {d["diary_id"] for d in second["diaries"]}


def test_cursor_must_be_posted_in_same_room(client):
    signup(client)
    room_id = make_room(client)["room_id"]
    other = make_room(client)["room_id"]
    response = client.post(
        f"/api/rooms/{other}/diaries", json={"request_id": str(uuid.uuid4()), "body": "소식", "mood": "GOOD"}
    )
    diary_id = response.json()["diary_id"]
    for invalid in (diary_id, -1):
        response = client.get(f"/api/rooms/{room_id}/diaries?before={invalid}")
        assert response.status_code == 404 and response.json()["code"] == "DIARY_NOT_FOUND"
    with SessionLocal() as db:
        diary = db.get(Diary, diary_id)
        diary.room_id = room_id
        diary.status = "DELETED"
        db.commit()
    # 같은 방의 지운 일기는 기준으로 쓴다 — 보는 사이 지워져도 다음 쪽이 끊기지 않게(다듬기 11/17)
    assert client.get(f"/api/rooms/{room_id}/diaries?before={diary_id}").status_code == 200
    client.cookies.clear()
    assert client.get(f"/api/rooms/{room_id}/diaries").status_code == 401
