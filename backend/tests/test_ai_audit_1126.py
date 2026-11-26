"""11/26 AI 전체 점검 고침 (D114): 위급이 겹칠 때·위로 중 몸 위급·마음 체크 다시 하기·말로 답하기·일기 '그만'·낱말 목록.

유료 API 는 부르지 않는다: call_json 을 바꿔 모델 출력을 흉내 낸다.
"""

import uuid

from sqlalchemy import select

from app.ai import coach, llm
from app.ai.schemas import ComfortTurn, has_body_words, has_risk_words
from app.db import SessionLocal
from app.models import Diary, TalkSession
from tests.conftest import setup_elder
from tests.test_mood_signal import _say, _start
from tests.test_reactions import _diary
from tests.test_safety_1119 import _alert_kinds, _diary_signal


def _flag(sid) -> str:
    with SessionLocal() as db:
        return db.get(TalkSession, uuid.UUID(sid)).emotion_flag


# ---------------------------------------------------------------- 마음 위급 + 몸 위급이 한 말에
def test_risk_and_body_words_together_get_the_119_close(client):
    """약을 먹었고 지금 숨을 못 쉰다 — 위로 대화가 아니라 119 버튼과 몸 위급 알림. 기록은 마음 위급으로도 남는다."""
    ctx = setup_elder(client)
    sid = _start(client, ctx)
    out = _say(client, sid, "약 먹고 죽으려고 다 먹었어, 숨을 못 쉬겠어")
    assert (out["state"], out["urgent"]) == ("ENDED", "BODY")
    assert _alert_kinds(ctx["room_id"]) == ["BODY"]
    assert _flag(sid) == "RISK"


# ---------------------------------------------------------------- 위로 중 몸 위급
def _comfort_body_at(n):
    """위로 AI 가 n 번째 위로 말을 만들 때(= 직전 어르신 말을 보고) 몸 위급(BODY)을 본 것처럼."""
    real = llm.call_json

    def fake(name, data, schema):
        if name == "comfort":
            signal = "BODY" if data["turn_no"] == n else "NONE"
            return ComfortTurn(text="많이 힘드셨겠어요.", suggestions=[], question_type="NONE", signal=signal)
        return real(name, data, schema)

    return fake


def test_comfort_sees_body_danger_and_closes_with_119(client, monkeypatch):
    monkeypatch.setattr(llm, "call_json", _comfort_body_at(2))
    ctx = setup_elder(client)
    sid = _start(client, ctx)
    out = _say(client, sid, "요즘은 정말 죽고 싶어요")
    assert (out["state"], out["ai"]["care"]) == ("CONTINUE", True)
    out = _say(client, sid, "식은땀이 나고 속이 이상해")  # 낱말 목록에는 없는 말 — 위로 AI 가 본다
    assert (out["state"], out["urgent"]) == ("ENDED", "BODY")
    assert sorted(_alert_kinds(ctx["room_id"])) == ["BODY", "MOOD"]


# ---------------------------------------------------------------- 마음 체크 다시 하기
def test_same_day_phq9_retake_with_item9_still_alerts(client):
    """그날 첫 결과만 저장되지만, 다시 한 마음 체크의 9번(자해·죽음 생각) 답은 가족 급한 알림으로 간다."""
    ctx = setup_elder(client)
    r = client.post("/api/elder/mood-check", json={"kind": "PHQ9", "answers": [0] * 9})
    assert r.status_code == 200, r.text
    assert _alert_kinds(ctx["room_id"]) == []
    r = client.post("/api/elder/mood-check", json={"kind": "PHQ9", "answers": [0] * 8 + [1]})
    assert r.status_code == 200, r.text
    assert _alert_kinds(ctx["room_id"]) == ["MOOD"]


# ---------------------------------------------------------------- 가족 일기에 말로 답하기
def test_reply_draft_with_urgent_words_alerts_family(client):
    ctx = setup_elder(client)
    family = _diary(ctx["room_id"], "FAMILY")
    r = client.post(f"/api/elder/diaries/{family}/reply-draft", json={"transcript": "고맙다 근데 나는 죽고 싶다"})
    assert r.status_code == 200, r.text
    assert _alert_kinds(ctx["room_id"]) == ["MOOD"]
    r = client.post(f"/api/elder/diaries/{family}/reply-draft", json={"transcript": "넘어졌는데 못 일어나겠어"})
    assert r.status_code == 200, r.text
    assert sorted(_alert_kinds(ctx["room_id"])) == ["BODY", "MOOD"]


# ---------------------------------------------------------------- 일기 대화 '그만'
def test_diary_stop_signal_ends_without_a_diary(client, monkeypatch):
    monkeypatch.setattr(llm, "call_json", _diary_signal("STOP"))
    ctx = setup_elder(client)
    sid = _start(client, ctx, kind="DIARY")
    out = _say(client, sid, "오늘은 그만할래")
    assert (out["state"], out["end_reason"], out["ai"]["text"]) == ("ENDED", "USER_STOP", coach.DIARY_STOP.text)
    with SessionLocal() as db:
        assert db.scalar(select(Diary.diary_id).where(Diary.room_id == ctx["room_id"])) is None


# ---------------------------------------------------------------- 낱말 목록
def test_new_urgent_words_and_old_false_positive():
    for said in ("자고 일어나지 않았으면 좋겠어", "그냥 죽고 십다", "세상 떠나고 싶어", "목매달고 싶다"):
        assert has_risk_words(said), said
    assert not has_risk_words("자식한테 목매고 살았지")  # 매달리며 살았다는 옛말 — 위급 아님
    for said in ("갑자기 한쪽 팔에 힘이 없어", "가슴이 조여 와", "넘어졌는데 못 일어나"):
        assert has_body_words(said), said


# ---------------------------------------------------------------- 어르신 대화 공통 규칙
def test_elder_talk_prompts_share_one_common_block():
    """위급 판단 기준·약속·약 규칙은 _elder_common.md 한 곳 — 어르신 대화 프롬프트 4개에만 붙는다."""
    for name in llm.ELDER_TALK:
        assert "# 위급 판단 기준" not in (llm.PROMPTS_DIR / f"{name}.md").read_text("utf-8")
        assert "## 위급 판단 기준" in llm.load_prompt(name), name
    assert "위급 판단 기준" not in llm.load_prompt("weekly_summary")
