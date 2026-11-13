"""마음 신호 (D55): LOW 는 기록하고 이어 감, 위급(AI·낱말)은 가족에게 바로 알리고 마무리, 7일 중 2일, 비밀 부탁."""

import uuid
from datetime import timedelta

from sqlalchemy import func, select

from app.ai import coach, llm
from app.ai.schemas import CoachTurn, has_risk_words
from app.config import now_kst
from app.db import SessionLocal
from app.models import Notification, TalkSession
from tests.conftest import setup_elder


def _signal(turn_no, signal, private=False):
    """turn_no 번째 회상 질문을 만들 때(=그 앞 답을 보고) 모델이 signal 을 낸 것처럼."""
    real = llm.call_json

    def fake(name, data, schema):
        if name == "memory_coach" and not data["closing"] and data["turn_no"] == turn_no:
            text = "요즘 기운이 없으시군요. 좋아하시는 음식이 있으세요?"
            return CoachTurn(text=text, suggestions=["국수요", "떡이요"], signal=signal, private=private)
        return real(name, data, schema)

    return fake


def _start(client, ctx, kind="MEMORY"):
    body = {"session_id": str(uuid.uuid4()), "kind": kind}
    if kind == "MEMORY":
        body["pick_id"] = ctx["pick"]["pick_id"]
    r = client.post("/api/elder/sessions", json=body)
    assert r.status_code == 201, r.text
    return r.json()["session_id"]


def _say(client, sid, text="네, 기억나요"):
    r = client.post(f"/api/elder/sessions/{sid}/turns", json={"text": text, "input_type": "CHIP"})
    assert r.status_code == 200, r.text
    return r.json()


def _row(sid):
    with SessionLocal() as db:
        s = db.get(TalkSession, uuid.UUID(sid))
        return s.emotion_flag, s.private_flag


def _notes(room_id, kind):
    with SessionLocal() as db:
        return db.scalar(
            select(func.count())
            .select_from(Notification)
            .where(Notification.room_id == room_id, Notification.kind == kind)
        )


def test_risk_words():
    for said in ("요즘은 정말 죽고 싶어요", "살기 싫어", "죽고 싶 어", "이제 그만 살고 싶어", "자살"):
        assert has_risk_words(said), said
    for said in ("좋아 죽겠어요", "배고파 죽겠네", "웃겨 죽는 줄 알았어", "살 빼고 싶어", "그때는 참 살기 좋았지"):
        assert not has_risk_words(said), said


def test_low_is_recorded_and_talk_goes_on(client, monkeypatch):
    monkeypatch.setattr(llm, "call_json", _signal(2, "LOW"))
    ctx = setup_elder(client)
    sid = _start(client, ctx)
    r = _say(client, sid, "몰라, 그냥 그래")
    assert r["state"] == "CONTINUE" and r["turn_no"] == 2 and r["ai"]["question_type"] == "RECALL"
    assert _row(sid) == ("LOW", False)
    assert _notes(ctx["room_id"], "MOOD_URGENT") == 0 and _notes(ctx["room_id"], "MOOD_LOW_2D") == 0  # 하루뿐


def test_risk_by_model_alerts_family_once_and_closes(client, monkeypatch):
    monkeypatch.setattr(llm, "call_json", _signal(2, "RISK"))
    ctx = setup_elder(client)
    sid = _start(client, ctx)
    r = _say(client, sid, "다 귀찮고 힘들어")
    assert r["state"] == "ENDED" and r["end_reason"] == "COMPLETED"
    assert r["ai"]["text"] == coach.RISK_CLOSING.text and r["ai"]["suggestions"] == []
    assert _row(sid)[0] == "RISK"
    assert _notes(ctx["room_id"], "MOOD_URGENT") == 1  # 가족 1명 = 1건
    with SessionLocal() as db:  # 알림에 대화 내용이 들어가지 않는다
        n = db.scalars(select(Notification).where(Notification.kind == "MOOD_URGENT")).first()
        assert "귀찮" not in (n.title + (n.body or ""))


def test_risk_words_close_even_when_model_says_nothing(client):
    ctx = setup_elder(client)  # mock 모델은 늘 NONE — 낱말 안전망만으로 잡는다
    sid = _start(client, ctx)
    r = _say(client, sid, "요즘은 그냥 죽고 싶어")
    assert r["state"] == "ENDED" and r["ai"]["text"] == coach.RISK_CLOSING.text and _row(sid)[0] == "RISK"
    assert _notes(ctx["room_id"], "MOOD_URGENT") == 1

    sid2 = _start(client, ctx, "ALBUM")
    r = _say(client, sid2, "손주들 보면 좋아 죽겠어")
    assert r["state"] == "CONTINUE" and _row(sid2)[0] == "NONE"


def test_risk_in_diary_is_not_saved_as_diary(client):
    ctx = setup_elder(client)
    sid = _start(client, ctx, "DIARY")
    r = _say(client, sid, "살기 싫어")
    assert r["state"] == "ENDED" and r["end_reason"] == "USER_STOP" and _row(sid)[0] == "RISK"
    assert _notes(ctx["room_id"], "MOOD_URGENT") == 1


def _past_low(room_id, days_ago, private=False):
    with SessionLocal() as db:
        db.add(
            TalkSession(
                session_id=uuid.uuid4(),
                room_id=room_id,
                kind="MEMORY",
                input_mode="VOICE",
                started_at=now_kst() - timedelta(days=days_ago),
                emotion_flag="LOW",
                private_flag=private,
            )
        )
        db.commit()


def test_low_on_two_days_in_a_week_alerts_once(client, monkeypatch):
    monkeypatch.setattr(llm, "call_json", _signal(2, "LOW"))
    ctx = setup_elder(client)
    _past_low(ctx["room_id"], 8)  # 7일 밖 — 세지 않음
    _past_low(ctx["room_id"], 3, private=True)  # 비밀 부탁 대화 — 세지 않음
    _say(client, _start(client, ctx))
    assert _notes(ctx["room_id"], "MOOD_LOW_2D") == 0

    _past_low(ctx["room_id"], 2)
    _say(client, _start(client, ctx, "ALBUM"))  # 오늘 + 이틀 전 = 2일
    assert _notes(ctx["room_id"], "MOOD_LOW_2D") == 1
    _say(client, _start(client, ctx, "ALBUM"))  # 같은 7일 안에는 다시 안 감
    assert _notes(ctx["room_id"], "MOOD_LOW_2D") == 1


def test_private_request_marks_session(client, monkeypatch):
    monkeypatch.setattr(llm, "call_json", _signal(2, "NONE", private=True))
    ctx = setup_elder(client)
    sid = _start(client, ctx)
    r = _say(client, sid, "이건 애들한테 말하지 마")
    assert r["state"] == "CONTINUE" and _row(sid) == ("NONE", True)
