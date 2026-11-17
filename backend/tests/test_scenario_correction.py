"""틀린 분류를 가족이 고친 뒤 회상 대화와 문제에 반영한다 (시나리오 2)."""

import uuid
from datetime import timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.ai import llm
from app.config import MAX_TURNS, QUIZ_TURN, now_kst
from app.db import SessionLocal
from app.models import FamilyRoom, Photo, QuestionBank, TalkSession
from tests.conftest import connect_device, make_room, signup
from tests.test_photos import _jpeg


@pytest.mark.parametrize("corrected", ["모내기", "none"])
def test_family_correction_drives_memory_context_and_quiz(client, question_bank, monkeypatch, corrected):
    signup(client)
    room_id = make_room(client)["room_id"]
    uploaded = client.post(
        f"/api/rooms/{room_id}/photos", files=[("files", (f"p{i}.jpg", _jpeg(), "image/jpeg")) for i in range(3)]
    )
    assert uploaded.status_code == 201
    photo_id = uploaded.json()["photos"][0]["photo_id"]
    with SessionLocal() as db:
        for photo in db.scalars(select(Photo).where(Photo.room_id == room_id)):
            photo.uploaded_at = now_kst() - timedelta(days=1)
            photo.activity, photo.category = "김장", "none"
            photo.analyzed_at, photo.confidence = now_kst(), Decimal("0.90")
            photo.usable = photo.photo_id == photo_id
        db.get(FamilyRoom, room_id).memory_time = __import__("datetime").time(0)
        db.commit()
    correction = client.patch(
        f"/api/rooms/{room_id}/photos/{photo_id}/correction", json={"corrected_activity": corrected}
    )
    assert correction.status_code == 200
    connect_device(client, room_id)
    captured = []
    real = llm.call_json

    def record(name, data, schema):
        captured.append((name, data))
        return real(name, data, schema)

    monkeypatch.setattr(llm, "call_json", record)
    pick = client.get("/api/elder/home").json()["today_pick"]
    start = client.post(
        "/api/elder/sessions", json={"session_id": str(uuid.uuid4()), "kind": "MEMORY", "pick_id": pick["pick_id"]}
    )
    assert start.status_code == 201
    sid = start.json()["session_id"]
    assert captured[0][1]["photo"]["activity"] == (None if corrected == "none" else corrected)
    for _ in range(QUIZ_TURN - 1):
        turn = client.post(f"/api/elder/sessions/{sid}/turns", json={"text": "기억나요", "input_type": "CHIP"})
        assert turn.status_code == 200
    assert turn.json()["ai"]["question_type"] == ("THEN_NOW" if corrected == "none" else "KNOWHOW")
    for _ in range(MAX_TURNS - QUIZ_TURN + 1):
        turn = client.post(f"/api/elder/sessions/{sid}/turns", json={"text": "좋았어요", "input_type": "CHIP"})
        assert turn.status_code == 200
    assert turn.json()["state"] == "ENDED"
    with SessionLocal() as db:
        session = db.get(TalkSession, uuid.UUID(sid))
        (code,) = [t["question_code"] for t in session.turns if t.get("question_code")]
        question = db.scalar(select(QuestionBank).where(QuestionBank.code == code))
        assert question.activity == (None if corrected == "none" else corrected)
