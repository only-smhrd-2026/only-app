"""11/19 안전 고침: S2 잘 못 들은 말 속 위급 낱말 · S3 일기 대화의 AI 신호 · S9 마음 체크 '많이 힘드심' 가족 알림.

유료 API 는 부르지 않는다: call_json 을 바꿔 모델 출력을 흉내 낸다.
"""

import uuid

import pytest
from pydantic import ValidationError
from sqlalchemy import func, select

from app.ai import coach, llm
from app.ai.schemas import CoachTurn, DiaryTurn
from app.config import STT_FAIL_LOCK
from app.db import SessionLocal
from app.models import Diary, Notification, TalkSession, UrgentAlert
from tests.conftest import setup_elder
from tests.test_mood_signal import _say, _start


def _count(room_id, kind) -> int:
    with SessionLocal() as db:
        return db.scalar(
            select(func.count())
            .select_from(Notification)
            .where(Notification.room_id == room_id, Notification.kind == kind)
        )


def _alert_kinds(room_id) -> list[str]:
    with SessionLocal() as db:
        return list(db.scalars(select(UrgentAlert.kind).where(UrgentAlert.room_id == room_id)))


def _unsure(client, sid, text) -> dict:
    """음성 인식이 불확실한 답 (신뢰도 0.3)."""
    body = {"text": text, "input_type": "VOICE", "stt_confidence": 0.3}
    r = client.post(f"/api/elder/sessions/{sid}/turns", json=body)
    assert r.status_code == 200, r.text
    return r.json()


# ---------------------------------------------------------------- S2
def test_unsure_voice_with_risk_words_is_not_read_back(client):
    ctx = setup_elder(client)
    sid = _start(client, ctx)
    out = _unsure(client, sid, "요즘은 정말 죽고 싶어요")
    # 되묻지 않는다("제가 '죽고 싶어요' 라고 들었어요" 금지) — 바로 위급 마무리 + 가족 알림
    assert (out["state"], out["ai"]["text"]) == ("ENDED", coach.RISK_CLOSING.text)
    assert _count(ctx["room_id"], "MOOD_URGENT") == 1 and _alert_kinds(ctx["room_id"]) == ["MOOD"]
    with SessionLocal() as db:
        said = db.get(TalkSession, uuid.UUID(sid)).turns[-2]
    assert (said["speaker"], said["stt_confidence"]) == ("ELDER", 0.3)  # 낮은 신뢰도 그대로 남긴다


def test_unsure_voice_with_body_words_gets_the_119_button(client):
    ctx = setup_elder(client)
    out = _unsure(client, _start(client, ctx), "방금 넘어져서 못 일어나겠어")
    assert (out["state"], out["urgent"]) == ("ENDED", "BODY")
    assert _alert_kinds(ctx["room_id"]) == ["BODY"]


def test_locked_voice_with_risk_words_is_still_urgent(client):
    """잘 못 들은 말이 쌓여 말하기가 잠긴 뒤에 온 음성이라도, 위급 낱말이 있으면 버리지 않는다 (11/19)."""
    ctx = setup_elder(client)
    sid = _start(client, ctx)
    for _ in range(STT_FAIL_LOCK):
        _unsure(client, sid, "어 그게 뭐더라")
    out = _unsure(client, sid, "요즘은 정말 죽고 싶어요")
    assert (out["state"], out["ai"]["text"]) == ("ENDED", coach.RISK_CLOSING.text)
    assert _count(ctx["room_id"], "MOOD_URGENT") == 1 and _alert_kinds(ctx["room_id"]) == ["MOOD"]


def test_unsure_voice_without_urgent_words_is_still_confirmed(client):
    ctx = setup_elder(client)
    sid = _start(client, ctx)
    out = _unsure(client, sid, "바닷가에 갔던 것 같아")
    assert out["state"] == "CONTINUE" and out["ai"]["suggestions"] == coach.CONFIRM_SUGGESTIONS
    with SessionLocal() as db:
        assert all(t["speaker"] == "AI" for t in db.get(TalkSession, uuid.UUID(sid)).turns)  # 아직 저장 안 함
    assert _count(ctx["room_id"], "MOOD_URGENT") == 0


# ---------------------------------------------------------------- S3
def _diary_signal(signal, turn_no=2):
    """일기 동무 AI 가 그 질문을 만들 때(= 그 앞 답을 보고) signal 을 낸 것처럼. 그 밖의 호출은 원래대로."""
    real = llm.call_json

    def fake(name, data, schema):
        if name == "diary_buddy" and data["turn_no"] == turn_no:
            text = "기운이 없으셨군요. 누구랑 계셨어요?"
            return DiaryTurn(text=text, suggestions=["혼자요", "가족이랑요"], question_type="NONE", signal=signal)
        return real(name, data, schema)

    return fake


def test_diary_low_signal_is_recorded_and_talk_goes_on(client, monkeypatch):
    monkeypatch.setattr(llm, "call_json", _diary_signal("LOW"))
    ctx = setup_elder(client)
    sid = _start(client, ctx, kind="DIARY")
    out = _say(client, sid, "종일 누워만 있었어")
    assert out["state"] == "CONTINUE"
    with SessionLocal() as db:
        session = db.get(TalkSession, uuid.UUID(sid))
        assert session.emotion_flag == "LOW" and session.turns[-1]["signal"] == "LOW"  # 내일 안부의 재료


def test_diary_risk_signal_closes_without_a_diary(client, monkeypatch):
    monkeypatch.setattr(llm, "call_json", _diary_signal("RISK"))
    ctx = setup_elder(client)
    sid = _start(client, ctx, kind="DIARY")
    out = _say(client, sid, "나는 이제 짐만 돼, 빨리 가야지")  # 낱말 안전망에는 안 걸리는 돌려 말하기
    assert (out["state"], out["end_reason"], out["ai"]["text"]) == ("ENDED", "USER_STOP", coach.RISK_CLOSING.text)
    assert _count(ctx["room_id"], "MOOD_URGENT") == 1 and _alert_kinds(ctx["room_id"]) == ["MOOD"]
    with SessionLocal() as db:
        assert db.scalar(select(Diary.diary_id).where(Diary.room_id == ctx["room_id"])) is None


def test_diary_body_signal_and_signal_before_any_answer(client, monkeypatch):
    monkeypatch.setattr(llm, "call_json", _diary_signal("BODY", turn_no=1))
    ctx = setup_elder(client)
    sid = _start(client, ctx, kind="DIARY")  # 어르신 말 전의 신호는 무시한다 — 대화가 그대로 열린다
    assert _alert_kinds(ctx["room_id"]) == []
    monkeypatch.setattr(llm, "call_json", _diary_signal("BODY"))
    out = _say(client, sid, "가슴이 답답하고 어지러워")
    assert (out["state"], out["end_reason"], out["urgent"]) == ("ENDED", "USER_STOP", "BODY")
    assert _alert_kinds(ctx["room_id"]) == ["BODY"]


# ---------------------------------------------------------------- S9
def test_hard_mood_check_tells_family_once(client):
    ctx = setup_elder(client)
    answers = [3, 3, 3, 3, 0, 0, 0, 0]  # 합 12 → '많이 힘드신 것 같아요'
    said = client.post("/api/elder/mood-check", json={"answers": answers}).json()["say"]
    assert said.endswith("가족에게도 요즘 힘드시다고 알릴게요. 말씀해 주셔서 고마워요.")
    assert _count(ctx["room_id"], "MOOD_LOW_2D") == 1
    client.post("/api/elder/mood-check", json={"answers": answers})  # 같은 날 다시 보내도 알림은 1건
    assert _count(ctx["room_id"], "MOOD_LOW_2D") == 1
    with SessionLocal() as db:
        body = db.scalar(select(Notification.body).where(Notification.kind == "MOOD_LOW_2D"))
    assert "12" not in body and "점" not in body  # 점수는 가족에게도 보내지 않는다


def test_down_mood_check_is_quiet_and_hard_without_named_item(client):
    ctx = setup_elder(client)
    down = client.post("/api/elder/mood-check", json={"answers": [1, 1, 1, 1, 1, 0, 0, 0]}).json()
    assert down["say"] is None and _count(ctx["room_id"], "MOOD_LOW_2D") == 0
    ctx2 = setup_elder(client)
    hard = client.post("/api/elder/mood-check", json={"answers": [1, 1, 1, 1, 0, 3, 3, 3]}).json()
    assert hard["say"].startswith("요즘 힘든 날이 많으셨군요.")  # 안부로 삼는 문항이 없어도 인사는 한다
    assert _count(ctx2["room_id"], "MOOD_LOW_2D") == 1


# ---------------------------------------------------------------- 위급 신호의 모델 말은 검사하지 않는다
def test_urgent_signal_text_is_not_validated_so_no_second_call():
    long_text = (
        "할머니, 지금 가슴이 조이고 식은땀이 나신다니 많이 놀라셨겠어요. 괜찮으세요? 바로 도움을 청해 주세요?" * 2
    )
    for schema in (CoachTurn, DiaryTurn):
        assert schema.model_validate({"text": long_text, "suggestions": ["너무 긴 추천 답변이에요"], "signal": "BODY"})
        with pytest.raises(ValidationError):  # 평소 신호면 길이·물음표 규칙 그대로
            schema.model_validate({"text": long_text, "suggestions": [], "signal": "NONE"})
