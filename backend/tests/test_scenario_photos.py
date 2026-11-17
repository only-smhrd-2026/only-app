"""사진 업로드부터 마무리까지 다섯 사진 종류의 문제 우선순위를 확인한다 (시나리오 1)."""

import json
import uuid
from datetime import timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.ai import quiz
from app.config import MAX_TURNS, QUIZ_TURN, ROOT, now_kst
from app.db import SessionLocal
from app.models import DailyPick, FamilyRoom, Photo, QuestionBank, TalkSession
from tests.conftest import connect_device, make_room, signup
from tests.test_photos import _jpeg


@pytest.mark.parametrize(
    "activity,category",
    [
        ("잔치", "잔칫상 음식"),
        ("모내기", "농기구"),
        ("none", "none"),
        ("none", "봄꽃"),
        ("none", "아이들 놀이"),
    ],
    ids=["feast", "rice-planting", "group", "landscape", "grandchild"],
)
def test_photo_kind_upload_quiz_and_finish(client, question_bank, activity, category):
    taxonomy = json.loads((ROOT / "data/taxonomy.json").read_text("utf-8"))
    assert activity in [*taxonomy["activity"], "none"] and category in [*taxonomy["category"], "none"]
    signup(client)
    room_id = make_room(client)["room_id"]
    upload = client.post(
        f"/api/rooms/{room_id}/photos", files=[("files", (f"photo{i}.jpg", _jpeg(), "image/jpeg")) for i in range(3)]
    )
    assert upload.status_code == 201
    with SessionLocal() as db:
        for photo in db.scalars(select(Photo).where(Photo.room_id == room_id)):
            photo.uploaded_at = now_kst() - timedelta(days=1)
            photo.activity, photo.category = activity, category
            photo.analyzed_at, photo.confidence = now_kst(), Decimal("0.90")
        db.get(FamilyRoom, room_id).memory_time = __import__("datetime").time(0, 0)
        db.commit()
    connect_device(client, room_id)
    seen = []
    # 과거 기록으로 옮겨 하루 상한과 분리해 14일 안의 문제 우선순위를 끝까지 관찰한다.
    for _ in range(12):
        with SessionLocal() as db:
            for pick in db.scalars(select(DailyPick).where(DailyPick.room_id == room_id)):
                pick.status = "PENDING"
            db.commit()
        home = client.get("/api/elder/home").json()
        with SessionLocal() as db:
            bank = db.scalars(select(QuestionBank)).all()
            expected = quiz.choose(
                bank,
                activity if activity != "none" else None,
                category if category != "none" else None,
                [(c, at) for c, at, _ in quiz.history(db, room_id)],
                now_kst().date(),
            )
            expected_code, expected_type = expected.code, expected.qtype
        response = client.post(
            "/api/elder/sessions",
            json={"session_id": str(uuid.uuid4()), "kind": "MEMORY", "pick_id": home["today_pick"]["pick_id"]},
        )
        assert response.status_code == 201
        sid = response.json()["session_id"]
        for _ in range(QUIZ_TURN - 1):
            response = client.post(f"/api/elder/sessions/{sid}/turns", json={"text": "기억나요", "input_type": "CHIP"})
            assert response.status_code == 200
        assert response.json()["ai"]["question_type"] == expected_type
        for _ in range(MAX_TURNS - QUIZ_TURN + 1):
            response = client.post(f"/api/elder/sessions/{sid}/turns", json={"text": "좋았어요", "input_type": "CHIP"})
            assert response.status_code == 200
        assert response.json()["state"] == "ENDED"
        with SessionLocal() as db:
            session = db.get(TalkSession, uuid.UUID(sid))
            assert [t["question_code"] for t in session.turns if t.get("question_code")] == [expected_code]
            session.started_at -= timedelta(days=1)
            session.turns = [dict(t, created_at=(now_kst() - timedelta(days=1)).isoformat()) for t in session.turns]
            db.commit()
        seen.append(expected_type)
        if expected_type == "COMMON":
            break
    assert "COMMON" in seen
    priority = {"KNOWHOW": 0, "REMEMBER": 1, "THEN_NOW": 2, "COMMON": 3}
    assert [priority[t] for t in seen] == sorted(priority[t] for t in seen)
