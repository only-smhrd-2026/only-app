"""어제 API 대화 → 새벽 추출 → 오늘 질문 → 거부 후 재사용 방지 (시나리오 4)."""

import uuid
from datetime import time, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.ai import llm, story
from app.ai.schemas import CoachTurn
from app.config import now_kst, today_kst
from app.db import SessionLocal
from app.models import FamilyRoom, Photo, StoryFact, TalkSession
from tests.conftest import connect_device, make_room, signup
from tests.test_photos import _jpeg
from tests.test_story import _say, _start, _turns


@pytest.mark.parametrize("age", [1, 8], ids=["yesterday", "eight-days-ago"])
def test_extract_then_first_question_and_denial(client, monkeypatch, age):
    signup(client)
    room_id = make_room(client)["room_id"]
    upload = client.post(
        f"/api/rooms/{room_id}/photos", files=[("files", (f"p{i}.jpg", _jpeg(), "image/jpeg")) for i in range(3)]
    )
    assert upload.status_code == 201
    with SessionLocal() as db:
        for photo in db.scalars(select(Photo).where(Photo.room_id == room_id)):
            photo.uploaded_at = now_kst() - timedelta(days=1)
            photo.activity, photo.category = "모내기", "농기구"
            photo.analyzed_at, photo.confidence = now_kst(), Decimal("0.90")
        db.get(FamilyRoom, room_id).memory_time = time(0)
        db.commit()
    connect_device(client, room_id)
    ctx = {"room_id": room_id, "pick": client.get("/api/elder/home").json()["today_pick"]}
    first = _start(client, ctx["pick"]["pick_id"])
    sid = first["session_id"]
    _say(client, sid, "마당에서 가족과 국화를 심었어요")
    assert client.post(f"/api/elder/sessions/{sid}/end", json={"reason": "USER_STOP"}).status_code == 200
    day = today_kst() - timedelta(days=age)
    with SessionLocal() as db:
        session = db.get(TalkSession, uuid.UUID(sid))
        session.started_at = now_kst() - timedelta(days=age)
        session.ended_at = session.started_at + timedelta(minutes=1)
        session.turns = [dict(t, created_at=session.started_at.isoformat()) for t in session.turns]
        db.commit()
        rooms, kept = story.run(db, day)
        assert rooms >= 1 and kept >= 1
        fact = db.scalar(select(StoryFact).where(StoryFact.room_id == ctx["room_id"]))
        assert fact is not None and fact.source_turn_no == 2
        fact_id = fact.fact_id
    captured = []
    real = llm.call_json

    def fake(name, data, schema):
        captured.append((name, data))
        if name == "memory_coach" and any(t.get("story") for t in data["turns"]):
            return CoachTurn(text="제가 잘못 알았나 봐요. 이 사진 보니 어떠세요?", signal="DENY")
        return real(name, data, schema)

    monkeypatch.setattr(llm, "call_json", fake)
    today = _start(client, ctx["pick"]["pick_id"])
    first_turn = _turns(today["session_id"])[0]
    if age == 8:
        assert "fact_id" not in first_turn
        assert all(name != "story_question" for name, _ in captured)
        return
    assert first_turn["fact_id"] == fact_id
    assert captured[0][0] == "story_question"
    assert "국화" in str(captured[0][1])
    with SessionLocal() as db:
        assert db.get(StoryFact, fact_id).used_at is not None
    second = _start(client, ctx["pick"]["pick_id"])
    assert "fact_id" not in _turns(second["session_id"])[0]
    _say(client, today["session_id"], "그런 말 안 했어")
    with SessionLocal() as db:
        fact = db.get(StoryFact, fact_id)
        assert fact.is_active is False
        # 다음 날에도 거부한 기억을 고르지 않는지 확인한다.
        monkeypatch.setattr(story, "today_kst", lambda: day + timedelta(days=2))
        assert story.pick(db, ctx["room_id"]) is None
