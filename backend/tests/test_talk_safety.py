"""거친 말·뜻 모를 말 (D112, 11/26 선생님 피드백) + 잡담도 주간 이야기에 (11/26 사용자).

- 뜻 모를 말(UNCLEAR, 글로 막 친 '푸엥츠'): 답으로 받지 않는다 — 저장·질문 수 그대로, 같은 질문을 다시.
- 거친 말(RUDE, AI 신호나 낱말): 대화는 잇고 그 어르신 말에 rude 표시 → 일기 초안·주간 카드에서 빠지고,
  한 주에 WEEKLY_RUDE_MIN 번이면 주간 '달라진 점'에 횟수만 한 줄.
"""

import uuid
from datetime import datetime

import pytest
from pydantic import ValidationError

from app.ai import coach, llm
from app.ai.schemas import ChatTurn, CoachTurn, DiaryTurn, has_rude_words
from app.config import TZ
from app.db import SessionLocal
from app.models import TalkSession
from tests.conftest import setup_elder
from tests.test_mood_signal import _start
from tests.test_weekly_ai import _room, _summarize, _talk
from tests.test_weekly_changes import _changes

MASH = "츠ㅜㅍ리암러"  # 11/26 선생님이 글로 쳐 본 말


def _type(client, sid, text):
    """어르신이 '글로 쓰기'로 친 말 — 음성이 아니라 확인 질문을 거치지 않는다."""
    r = client.post(f"/api/elder/sessions/{sid}/turns", json={"text": text, "input_type": "TEXT"})
    assert r.status_code == 200, r.text
    return r.json()


def _turns(sid):
    with SessionLocal() as db:
        return db.get(TalkSession, uuid.UUID(sid)).turns


def _elder(sid):
    return [t for t in _turns(sid) if t["speaker"] == "ELDER"]


def _fake(monkeypatch, name, said, reply):
    """name 프롬프트가 어르신 마지막 말 said 를 읽을 때만 reply 를 낸 것처럼. 나머지는 원래 mock."""
    real = llm.call_json

    def fake(prompt, data, schema):
        elder = [t for t in data["turns"] if t["speaker"] == "ELDER"]
        if prompt == name and elder and elder[-1]["text"] == said:
            return reply
        return real(prompt, data, schema)

    monkeypatch.setattr(llm, "call_json", fake)


def test_rude_words():
    for said in ("이 씨발 놈아", "개새끼야 저리 가", "존나 싫어", "섹스 하자"):
        assert has_rude_words(said), said
    # 띄어 쓴 평범한 말·옛날 이야기 낱말은 낱말로 잡지 않는다 (AI 가 맥락으로 본다)
    for said in (
        "수박 씨 발라 먹었지",
        "우리 개 새끼를 다섯 마리 낳았어",
        "시발택시 타 봤지",
        "병신년에 태어났어",
        "추위가 닥쳐서 혼났어",
        "꼭꼭 씹어 먹어",
        "양반 쌍놈 따지던 때",
        "보지 마세요",
    ):
        assert not has_rude_words(said), said
    with pytest.raises(ValidationError):  # AI 가 어르신 말을 되받다가 거친 말을 따라 하면 다시 쓰게 한다
        CoachTurn(text="지랄이라고 하셨군요. 또 뭐 하셨어요?")


def test_unclear_memory_asks_again_without_saving(client, monkeypatch):
    ctx = setup_elder(client)
    sid = _start(client, ctx)
    first = client.get(f"/api/elder/sessions/{sid}").json()["last_ai"]["text"]
    _fake(monkeypatch, "memory_coach", MASH, CoachTurn(text="제가 잘 못 알아들었어요.", signal="UNCLEAR"))
    out = _type(client, sid, MASH)
    assert out["ai"]["text"] == f"{coach.UNCLEAR_LEAD} {first}"
    assert (out["state"], out["turn_no"]) == ("CONTINUE", 1)  # 질문 수 그대로
    assert _elder(sid) == []  # 답으로 남지 않는다
    out = _type(client, sid, MASH)  # 몇 번이든 같다 — 앞말이 겹쳐 붙지 않는다
    assert out["ai"]["text"] == f"{coach.UNCLEAR_LEAD} {first}"
    out = _type(client, sid, "바닷가에 놀러 갔던 사진이야")
    assert out["turn_no"] == 2 and [t["text"] for t in _elder(sid)] == ["바닷가에 놀러 갔던 사진이야"]


def test_unclear_diary_fourth_answer_asks_again(client, monkeypatch):
    """일기 4번째 답 — 다음이 고정 기분 질문이어도 AI 가 읽는다. 뜻 모를 말이면 4번 질문을 다시."""
    setup_elder(client)
    sid = str(uuid.uuid4())
    r = client.post("/api/elder/sessions", json={"session_id": sid, "kind": "DIARY"})
    assert r.status_code == 201, r.text
    for said in ("시장에 다녀왔어", "영자랑 갔어", "두부 샀어"):
        fourth = _type(client, sid, said)["ai"]["text"]
    _fake(monkeypatch, "diary_buddy", MASH, DiaryTurn(text="다시 한 번 말씀해 주시겠어요?", signal="UNCLEAR"))
    out = _type(client, sid, MASH)
    assert (out["ai"]["text"], out["turn_no"]) == (f"{coach.UNCLEAR_LEAD} {fourth}", 4)
    out = _type(client, sid, "집에 와서 쉬었어")
    assert out["ai"]["text"] == coach.DIARY_MOOD_QUESTION.text and len(out["ai"]["suggestions"]) == 4
    assert MASH not in [t["text"] for t in _elder(sid)]


def test_unclear_chat(client, monkeypatch):
    setup_elder(client)
    sid = str(uuid.uuid4())
    assert client.post("/api/elder/sessions", json={"session_id": sid, "kind": "CHAT"}).status_code == 201
    _fake(monkeypatch, "chat_buddy", "푸엥츠", ChatTurn(text="제가 잘 못 알아들었어요.", signal="UNCLEAR"))
    out = _type(client, sid, "푸엥츠")
    assert out["ai"]["text"] == coach.CHAT_UNCLEAR.text and out["state"] == "CONTINUE"
    assert _elder(sid) == []


def test_rude_keeps_talking_and_is_marked(client, monkeypatch):
    ctx = setup_elder(client)
    sid = _start(client, ctx)
    line = "그런 말씀은 들으면 제가 조금 속상해요. 이 사진 보니 어떠세요?"
    _fake(monkeypatch, "memory_coach", "저리 가 이 못된 것아", CoachTurn(text=line, signal="RUDE"))
    out = _type(client, sid, "저리 가 이 못된 것아")  # 낱말 목록에 없는 말 — AI 가 본다
    assert (out["ai"]["text"], out["turn_no"], out["state"]) == (line, 2, "CONTINUE")
    _type(client, sid, "개새끼야")  # AI(mock)는 NONE 이어도 낱말이 잡는다
    _type(client, sid, "바닷가 사진이지")
    assert [t.get("rude", False) for t in _elder(sid)] == [True, True, False]


def test_rude_diary_lead_is_fixed(client, monkeypatch):
    """11/26 실측: 일기 모델이 거친 말에 '죄송해요'·못 들은 척 — 앞말은 고정, 모델 질문만 쓴다."""
    setup_elder(client)
    sid = str(uuid.uuid4())
    assert client.post("/api/elder/sessions", json={"session_id": sid, "kind": "DIARY"}).status_code == 201
    said = "씨발 이딴 거 왜 물어"
    _fake(monkeypatch, "diary_buddy", said, DiaryTurn(text="죄송해요. 오늘 하루는 어떻게 보내셨어요?", signal="RUDE"))
    out = _type(client, sid, said)
    assert out["ai"]["text"] == f"{coach.RUDE_LEAD} 오늘 하루는 어떻게 보내셨어요?"
    assert _elder(sid)[-1]["rude"] is True


def test_rude_answer_stays_out_of_diary_draft(monkeypatch):
    seen = {}

    def fail(name, data, schema):
        seen["turns"] = data["turns"]
        raise llm.LlmError(name)

    monkeypatch.setattr(llm, "call_json", fail)
    turns = [
        {"speaker": "AI", "text": "오늘은 뭐 하셨어요?"},
        {"speaker": "ELDER", "text": "시장에 갔어"},
        {"speaker": "AI", "text": "누구랑 가셨어요?"},
        {"speaker": "ELDER", "text": "개새끼야", "rude": True},
    ]
    draft = coach.diary_draft(coach.CoachContext("김순자", "할머니", turns=turns))
    assert [t["text"] for t in seen["turns"] if t["speaker"] == "ELDER"] == ["시장에 갔어"]
    assert draft.body == "시장에 갔어."


def _rude_talk(db, room_id, day, private=False):
    db.add(
        TalkSession(
            session_id=uuid.uuid4(),
            room_id=room_id,
            kind="MEMORY",
            input_mode="VOICE",
            started_at=datetime(2026, 11, day, 10, tzinfo=TZ),
            private_flag=private,
            emotion_flag="NONE",
            turns=[
                {"turn_no": 1, "speaker": "AI", "text": "이 사진 보니 어떠세요?"},
                {"turn_no": 2, "speaker": "ELDER", "text": "개새끼야 저리 가", "rude": True, "reply_to_turn_no": 1},
            ],
        )
    )


def test_weekly_counts_rude_and_takes_chat(client):
    """거친 말 2번(비밀 부탁 대화는 빼고) → 횟수만 한 줄. 잡담도 이야기한 날·카드에 든다. 거친 말은 카드에 없다."""
    room_id = _room(client)
    with SessionLocal() as db:
        _rude_talk(db, room_id, 10)
        _rude_talk(db, room_id, 11)
        _rude_talk(db, room_id, 12, private=True)
        _talk(db, room_id, 13, [("오늘은 뭐 하고 지내셨어요?", "손주 민준이가 반장이 됐대")], kind="CHAT")
        db.commit()
    row = _summarize(room_id)
    assert row.memory_days == 4
    assert [card["question"] for card in row.qa_list] == ["오늘은 뭐 하고 지내셨어요?"]
    assert ("RUDE", "watch", "대화 중에 거친 말이나 성적인 말을 하신 적이 2번 있었어요.") in _changes(client, room_id)


def test_weekly_one_rude_is_not_a_line(client):
    room_id = _room(client)
    with SessionLocal() as db:
        _rude_talk(db, room_id, 10)
        db.commit()
    _summarize(room_id)
    assert not [line for line in _changes(client, room_id) if line[0] == "RUDE"]
