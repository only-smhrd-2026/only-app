"""심심이 잡담 (D106, 11/25 멘토 아이디어) — 홈의 심심이를 누르면 아무 이야기나·궁금한 것 무엇이든.

키 없는 mock 이 '가자는 낱말'이면 그 화면(go)을, 아니면 고정 맞장구를 준다(llm._mock_chat).
"""

import uuid

import pytest
from pydantic import ValidationError

from app.ai import llm
from app.ai.schemas import ChatTurn
from app.config import CHAT_TURNS
from app.db import SessionLocal
from app.models import TalkSession
from app.services import weather
from tests.conftest import setup_elder


def _start(client, **extra):
    sid = str(uuid.uuid4())
    r = client.post("/api/elder/sessions", json={"session_id": sid, "kind": "CHAT"} | extra)
    return sid, r


def _say(client, sid, text, **extra):
    body = {"text": text, "input_type": "TEXT"} | extra
    return client.post(f"/api/elder/sessions/{sid}/turns", json=body).json()


def test_chat_start_and_go(client):
    setup_elder(client)
    sid, r = _start(client)
    assert r.status_code == 201, r.text
    first = r.json()
    assert first["kind"] == "CHAT" and first["ai"]["face"] == "hello" and first["ai"]["go"] is None
    assert first["photo_url"] is None and first["ai"]["suggestions"] == []  # 잡담은 답 버튼이 없다

    r = _say(client, sid, "오늘 시장 다녀왔어")
    assert r["state"] == "CONTINUE" and r["ai"]["go"] is None and r["ai"]["face"] == "joy"
    r = _say(client, sid, "사진첩 좀 보여 줘")
    assert r["ai"]["go"] == "ALBUM" and r["state"] == "CONTINUE"  # 화면이 사진첩으로 데려간다

    # 가자는 말 뒤 아무 말 없으면 같은 말을 다시 — 화면을 또 옮기지는 않는다
    r = client.post(f"/api/elder/sessions/{sid}/turns", json={"input_type": "BUTTON", "event": "NO_RESPONSE"}).json()
    assert r["ai"]["go"] is None and r["ai"]["text"]


@pytest.mark.parametrize(
    "text,go", [("오늘 일기 쓰자", "DIARY"), ("가족 소식 보여 줘", "NEWS"), ("마음 체크 할래", "MIND")]
)
def test_chat_go_each_screen(client, text, go):
    setup_elder(client)
    sid, _ = _start(client)
    assert _say(client, sid, text)["ai"]["go"] == go


def test_chat_runs_past_old_turn_cap_then_closes(client):
    """회상 상한(DB CHECK 0~8)을 넘어 20번까지 — 끝나면 질문 없는 마무리 인사."""
    setup_elder(client)
    sid, _ = _start(client)
    for i in range(CHAT_TURNS - 1):
        r = _say(client, sid, f"이야기 {i}")
        assert r["state"] == "CONTINUE", r
    assert r["turn_no"] == CHAT_TURNS
    r = _say(client, sid, "그랬지")
    assert r["state"] == "ENDED" and r["end_reason"] == "COMPLETED" and "?" not in r["ai"]["text"]


def test_chat_risk_words_comfort(client):
    """위급 낱말은 잡담에서도 AI 보다 먼저 — 위로를 잇고 가족에게 알린다 (D55·11/23 과 같은 길)."""
    setup_elder(client)
    sid, _ = _start(client)
    r = _say(client, sid, "요즘은 그냥 죽고 싶어")
    assert r["state"] == "CONTINUE" and r["ai"]["care"] is True
    with SessionLocal() as db:
        assert db.get(TalkSession, uuid.UUID(sid)).emotion_flag == "RISK"


def test_chat_list_and_resume(client):
    setup_elder(client)
    sid, _ = _start(client)
    _say(client, sid, "옛날 우물 이야기 해 줄게")
    _start(client)  # 말 없이 연 잡담은 목록에 없다

    r = client.get("/api/elder/sessions", params={"kind": "CHAT"})
    assert r.status_code == 200, r.text
    items = r.json()
    assert [i["session_id"] for i in items] == [sid]
    assert items[0]["title"] == "심심이랑 나눈 이야기" and items[0]["elder_turns"] == 1
    assert client.get("/api/elder/sessions").status_code == 422  # 잡담 목록만 — kind=CHAT 이 꼭 있어야

    sid2, r = _start(client, resume_of=sid)  # [이어서 하기]
    assert r.status_code == 201, r.text
    with SessionLocal() as db:
        assert db.get(TalkSession, uuid.UUID(sid2)).turns[0]["resume_of"] == sid
    _, r = _start(client, resume_of=str(uuid.uuid4()))
    assert r.status_code == 404


def test_chat_data_weather_family_today(client, monkeypatch):
    """AI 에 넘기는 데이터 — 동네 날씨(가족방 설정)·가족 이름·오늘 하신 것·말 번호."""
    ctx = setup_elder(client)
    seen = []
    real = llm.call_json

    def spy(name, data, schema, **kw):
        if name == "chat_buddy":
            seen.append(data)
        return real(name, data, schema, **kw)

    monkeypatch.setattr(llm, "call_json", spy)
    fake = {"where": "광주", "now": "맑음, 6도", "today": "맑음", "tomorrow": "흐림", "dust": "미세먼지 좋음"}
    monkeypatch.setattr(weather, "for_region", lambda region: fake if region == "광주" else None)

    r = client.patch(f"/api/rooms/{ctx['room_id']}/settings", json={"weather_region": "광주"})
    assert r.status_code == 200 and r.json()["weather_region"] == "광주"
    bad = client.patch(f"/api/rooms/{ctx['room_id']}/settings", json={"weather_region": "화성"})
    assert bad.status_code == 422

    sid, _ = _start(client)
    _say(client, sid, "오늘 날씨 어때")
    first, second = seen
    assert first["weather"] == fake and first["turn_no"] == 1 and first["turns"] == []
    assert first["family"] == ["테스터"] and first["elder_honorific"] == "할머니"
    assert set(first["today"]) == {"memory_done", "diary_done", "unread_family_news", "mood_due"}
    assert second["turn_no"] == 2 and second["turns"][-1] == {"speaker": "ELDER", "text": "오늘 날씨 어때"}


def test_chat_ai_failure_keeps_talking(client, monkeypatch):
    setup_elder(client)
    sid, _ = _start(client)

    def broken(*a, **kw):
        raise llm.LlmError("장애")

    monkeypatch.setattr(llm, "call_json", broken)
    r = _say(client, sid, "오늘 뭐 먹지")
    assert r["state"] == "CONTINUE" and "다시 한 번" in r["ai"]["text"]


def test_chat_turn_rules():
    ok = ChatTurn(text="와, 김치 열 포기요? 어떻게 담그셨어요?", topic="  김장  이야기 ")
    assert ok.topic == "김장 이야기"
    with pytest.raises(ValidationError):
        ChatTurn(text="뭐요? 왜요? 어디요?")  # 묻는 말은 하나 (되받는 감탄 포함 2개까지)
    with pytest.raises(ValidationError):
        ChatTurn(text="오늘 점수는 몇 점이에요?")  # 금지어
    urgent = ChatTurn.model_validate({"text": "아주 길고 길게 위로하는 말 " * 10, "signal": "RISK"})
    assert urgent.text == "네."  # 위급이면 코드 문장을 쓰므로 모델 말은 버린다(길이 검사에 걸려 늦지 않게)


def test_weather_words_and_failure(monkeypatch):
    assert weather.sky(0) == "맑음" and weather.sky(63) == "비" and weather.sky(95) == "천둥 번개"
    assert weather.dust(20, (30, 80, 150)) == "좋음" and weather.dust(81, (30, 80, 150)) == "나쁨"
    assert weather.for_region(None) is None and weather.for_region("화성") is None

    calls = []

    def down(region):
        calls.append(region)
        raise OSError("망 끊김")

    monkeypatch.setattr(weather, "_fetch", down)
    weather._cache.clear()
    assert weather.for_region("부산") is None
    assert weather.for_region("부산") is None and calls == ["부산"]  # 실패도 잠깐 기억 — 턴마다 기다리지 않게
    weather._cache.clear()
