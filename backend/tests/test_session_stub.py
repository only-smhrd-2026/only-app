"""세션 API 계약 — 6턴째 ENDED(D52 ⑦), 저신뢰 확인 질문·잠금, 무응답 3단계 (초석 D 완료 기준)."""

import uuid
from datetime import timedelta

from sqlalchemy import func, select, text
from sqlalchemy.exc import OperationalError

from app.ai import tts
from app.config import MAX_TURNS, now_kst, today_kst
from app.db import SessionLocal, engine
from app.models import DailyPick, Notification, TalkSession
from tests.conftest import setup_elder


def _create(client, ctx, kind="MEMORY"):
    body = {"session_id": str(uuid.uuid4()), "kind": kind, "pick_id": ctx["pick"]["pick_id"]}
    r = client.post("/api/elder/sessions", json=body)
    assert r.status_code == 201, r.text
    return r.json()


def test_max_turns_then_ended(client):
    ctx = setup_elder(client)
    s = _create(client, ctx)
    assert s["state"] == "CONTINUE" and s["turn_no"] == 1 and s["ai"]["text"]
    assert s["ai"]["choice_mode"] == "CHIPS" and 1 <= len(s["ai"]["suggestions"]) <= 3
    sid = s["session_id"]

    # 같은 session_id 재요청은 멱등
    again = client.post(
        "/api/elder/sessions", json={"session_id": sid, "kind": "MEMORY", "pick_id": ctx["pick"]["pick_id"]}
    )
    assert again.status_code == 201 and again.json()["turn_no"] == 1

    for i in range(MAX_TURNS - 1):
        r = client.post(f"/api/elder/sessions/{sid}/turns", json={"text": "네, 기억나요", "input_type": "CHIP"}).json()
        assert r["state"] == "CONTINUE" and r["turn_no"] == i + 2, r

    last = client.post(
        f"/api/elder/sessions/{sid}/turns", json={"text": "네", "input_type": "VOICE", "stt_confidence": 0.9}
    )
    body = last.json()
    assert body["state"] == "ENDED" and body["end_reason"] == "COMPLETED" and body["turn_no"] == MAX_TURNS == 6
    assert body["ai"]["question_type"] == "CLOSING"

    assert client.post(f"/api/elder/sessions/{sid}/turns", json={"text": "또", "input_type": "CHIP"}).status_code == 409
    got = client.get(f"/api/elder/sessions/{sid}").json()
    assert got["state"] == "ENDED" and got["end_reason"] == "COMPLETED"

    home = client.get("/api/elder/home").json()
    assert home["today_pick"]["status"] == "COMPLETED"
    assert client.post("/api/elder/picks/today/listened").status_code == 200


def test_low_confidence_confirm_then_lock(client):
    ctx = setup_elder(client)
    sid = _create(client, ctx)["session_id"]
    low = {"text": "웅얼웅얼", "input_type": "VOICE", "stt_confidence": 0.4}

    r = client.post(f"/api/elder/sessions/{sid}/turns", json=low).json()
    assert r["turn_no"] == 1 and r["ai"]["choice_mode"] == "TWO_BUTTONS" and r["input_locked"] is False
    assert r["ai"]["suggestions"] == ["맞아요", "다시 말할게요"]

    ok = client.post(f"/api/elder/sessions/{sid}/turns", json={**low, "retried": True}).json()  # "맞아요"
    assert ok["turn_no"] == 2

    r = client.post(f"/api/elder/sessions/{sid}/turns", json=low).json()
    assert r["input_locked"] is True  # 저신뢰 2회 → 잠금
    assert client.post(f"/api/elder/sessions/{sid}/turns", json=low).status_code == 409
    chip = client.post(f"/api/elder/sessions/{sid}/turns", json={"text": "좋았어요", "input_type": "CHIP"}).json()
    assert chip["turn_no"] == 3 and chip["input_locked"] is True


def test_no_response_three_stages_and_end(client):
    ctx = setup_elder(client)
    sid = _create(client, ctx)["session_id"]
    ev = {"input_type": "BUTTON", "event": "NO_RESPONSE"}
    r1 = client.post(f"/api/elder/sessions/{sid}/turns", json=ev).json()
    assert r1["state"] == "CONTINUE" and r1["turn_no"] == 1
    r2 = client.post(f"/api/elder/sessions/{sid}/turns", json=ev).json()
    assert r2["ai"]["choice_mode"] == "TWO_BUTTONS"
    r3 = client.post(f"/api/elder/sessions/{sid}/turns", json=ev).json()
    assert r3["state"] == "ENDED" and r3["end_reason"] == "NO_RESPONSE"

    sid2 = _create(client, ctx, kind="ALBUM")["session_id"]
    ended = client.post(f"/api/elder/sessions/{sid2}/end", json={"reason": "USER_STOP"}).json()
    assert ended["state"] == "ENDED" and ended["end_reason"] == "USER_STOP"


def _shift(sid: str, gaps: list[int]) -> None:
    """세션 시작·각 턴 시각을 과거로 옮긴다. gaps[0]=시작→1번 턴, …, gaps[-1]=마지막 턴→지금 (초)."""
    with SessionLocal() as db:
        s = db.get(TalkSession, uuid.UUID(sid))
        assert len(gaps) == len(s.turns) + 1
        t = now_kst() - timedelta(seconds=sum(gaps))
        s.started_at = t
        shifted = []
        for turn, gap in zip(s.turns, gaps):
            t += timedelta(seconds=gap)
            shifted.append(turn | {"created_at": t.isoformat()})
        s.turns = shifted
        db.commit()


def test_pause_resume_within_30min_then_stale(client):
    ctx = setup_elder(client)
    sid = _create(client, ctx)["session_id"]
    _shift(sid, [1, 20 * 60])  # 첫 질문 뒤 20분 보류 → 대화한 시간은 1+90초라 5분 상한에 안 걸림
    assert client.get(f"/api/elder/sessions/{sid}").json()["state"] == "CONTINUE"
    r = client.post(f"/api/elder/sessions/{sid}/turns", json={"text": "돌아왔어요", "input_type": "CHIP"}).json()
    assert r["state"] == "CONTINUE" and r["turn_no"] == 2

    _shift(sid, [1, 1, 1, 31 * 60])  # 마지막 턴 뒤 31분 → 끝난 대화
    assert client.get(f"/api/elder/sessions/{sid}").json()["state"] == "ENDED"
    stale = client.post(f"/api/elder/sessions/{sid}/turns", json={"text": "또", "input_type": "CHIP"})
    assert stale.status_code == 409 and stale.json()["code"] == "SESSION_ENDED"
    with SessionLocal() as db:
        assert db.get(TalkSession, uuid.UUID(sid)).end_reason == "NO_RESPONSE"


def test_limit_saves_last_answer_then_closes(client):
    ctx = setup_elder(client)
    sid = _create(client, ctx)["session_id"]
    for _ in range(3):
        client.post(f"/api/elder/sessions/{sid}/turns", json={"text": "네", "input_type": "CHIP"})
    _shift(sid, [80] * 8)  # 7행 + 지금 = 간격 8개 × 80초 = 640초 > 5분
    r = client.post(f"/api/elder/sessions/{sid}/turns", json={"text": "마지막 말이에요", "input_type": "CHIP"}).json()
    assert r["state"] == "ENDED" and r["end_reason"] == "LIMIT" and r["ai"]["question_type"] == "CLOSING"
    with SessionLocal() as db:
        texts = [t["text"] for t in db.get(TalkSession, uuid.UUID(sid)).turns]
    assert texts[-2] == "마지막 말이에요"  # 마무리 인사 바로 앞에 저장됨


def test_session_error_alert_on_third_error(client):
    ctx = setup_elder(client)

    def alerts() -> int:
        with SessionLocal() as db:
            return db.scalar(
                select(func.count())
                .select_from(Notification)
                .where(Notification.room_id == ctx["room_id"], Notification.kind == "SESSION_ERROR_3X")
            )

    for i in range(3):
        sid = _create(client, ctx, kind="ALBUM")["session_id"]
        assert client.post(f"/api/elder/sessions/{sid}/end", json={"reason": "ERROR"}).status_code == 200
        assert alerts() == (1 if i == 2 else 0), f"ERROR {i + 1}회째"


def test_low_confidence_echo_with_banned_word_is_not_500(client):
    ctx = setup_elder(client)
    sid = _create(client, ctx)["session_id"]
    body = {"text": "우리 아들이 저하고 같이 갔어요?? 맞나?", "input_type": "VOICE", "stt_confidence": 0.3}
    r = client.post(f"/api/elder/sessions/{sid}/turns", json=body)
    assert r.status_code == 200 and r.json()["ai"]["suggestions"] == ["맞아요", "다시 말할게요"]
    assert "저하" not in r.json()["ai"]["text"]


def test_old_or_skipped_pick_cannot_start(client):
    """옛 화면에서 누른 [이야기하기] (D45 ④): 어제 pick·건너뛴 pick 으로는 새 대화가 안 열린다.

    이미 연 대화를 같은 번호로 다시 요청하는 것은 그대로 된다.
    """
    ctx = setup_elder(client)
    pick_id = ctx["pick"]["pick_id"]
    opened = _create(client, ctx)  # 날이 바뀌기 전에 연 대화
    with SessionLocal() as db:  # 날이 바뀜: 오늘 pick 이 어제 것이 된다 (홈을 켜 둔 채 자정을 넘긴 폰)
        db.get(DailyPick, pick_id).pick_date = today_kst() - timedelta(days=1)
        db.commit()
    body = {"session_id": str(uuid.uuid4()), "kind": "MEMORY", "pick_id": pick_id}
    r = client.post("/api/elder/sessions", json=body)
    assert r.status_code == 409 and r.json()["code"] == "PICK_EXPIRED"
    again = client.post("/api/elder/sessions", json=body | {"session_id": opened["session_id"]})
    assert again.status_code == 201 and again.json()["session_id"] == opened["session_id"]  # 같은 번호 재요청은 멱등

    today = client.get("/api/elder/home").json()["today_pick"]  # 홈을 다시 읽으면 오늘 pick 이 새로 뽑힌다
    assert today["pick_id"] != pick_id and today["status"] == "PENDING"
    assert client.post("/api/elder/picks/today/skip").status_code == 200
    r = client.post("/api/elder/sessions", json=body | {"pick_id": today["pick_id"]})
    assert r.status_code == 409 and r.json()["code"] == "PICK_SKIPPED"
    with SessionLocal() as db:  # 거절된 요청은 대화를 만들지 않는다
        assert db.get(TalkSession, uuid.UUID(body["session_id"])) is None


def test_reask_and_confirm_release_row_lock_before_tts(client, monkeypatch):
    """재질문(무응답 1단계)·저신뢰 확인 질문은 음성을 만들기 전에 세션 행 잠금을 푼다 — 음성 합성은 몇 초가 걸린다."""
    ctx = setup_elder(client)
    sid = _create(client, ctx)["session_id"]
    locked = []

    def synth(sentence, speed):
        with engine.connect() as other:  # 다른 연결이 그 행을 바로 잡을 수 있어야 한다 (기다리지 않고 확인: NOWAIT)
            try:
                other.execute(text("SELECT 1 FROM sessions WHERE session_id = :id FOR UPDATE NOWAIT"), {"id": sid})
                locked.append(False)
            except OperationalError:
                locked.append(True)
        return b""

    monkeypatch.setattr(tts, "synthesize", synth)
    url = f"/api/elder/sessions/{sid}/turns"
    assert client.post(url, json={"input_type": "BUTTON", "event": "NO_RESPONSE"}).status_code == 200
    assert client.post(url, json={"text": "웅얼웅얼", "input_type": "VOICE", "stt_confidence": 0.4}).status_code == 200
    assert locked == [False, False]


def _elder_turns(sid: str) -> list[dict]:
    with SessionLocal() as db:
        return [t for t in db.get(TalkSession, uuid.UUID(sid)).turns if t["speaker"] == "ELDER"]


def test_low_confidence_yes_saves_heard_text_not_yes(client):
    """저신뢰 → 확인 질문 → '맞아요'(칩·말)면 '맞아요'가 아니라 들은 문장이 답으로 남는다 (D33 의 문제, D52 ③)."""
    ctx = setup_elder(client)
    low = {"text": "바다에 갔어요", "input_type": "VOICE", "stt_confidence": 0.5}
    sid = _create(client, ctx)["session_id"]
    url = f"/api/elder/sessions/{sid}/turns"
    assert client.post(url, json=low).json()["ai"]["suggestions"] == ["맞아요", "다시 말할게요"]
    r = client.post(url, json={"text": "맞아요", "input_type": "CHIP"}).json()
    assert r["turn_no"] == 2 and r["ai"]["question_type"] != "NONE"  # 다음 질문으로
    saved = _elder_turns(sid)[-1]
    assert saved["text"] == "바다에 갔어요" and saved["input_type"] == "VOICE"
    assert saved["retried"] is True and saved["stt_confidence"] == 0.5

    # '다시 말할게요'(칩) 면 저장 없이 원래 질문을 다시
    sid2 = _create(client, ctx, kind="ALBUM")["session_id"]
    q2 = client.get(f"/api/elder/sessions/{sid2}").json()["last_ai"]["text"]
    client.post(f"/api/elder/sessions/{sid2}/turns", json=low)
    again = client.post(f"/api/elder/sessions/{sid2}/turns", json={"text": "다시 말할게요", "input_type": "CHIP"})
    assert again.json()["ai"]["text"] == q2 and again.json()["turn_no"] == 1 and _elder_turns(sid2) == []

    # 말로 '네, 맞아요.' 도 같다 (저신뢰 2번이면 잠기므로 새 대화에서)
    sid3 = _create(client, ctx)["session_id"]
    client.post(f"/api/elder/sessions/{sid3}/turns", json={**low, "text": "산에 갔어요"})
    yes = {"text": "네, 맞아요.", "input_type": "VOICE", "stt_confidence": 0.95}
    r = client.post(f"/api/elder/sessions/{sid3}/turns", json=yes).json()
    assert r["turn_no"] == 2 and [t["text"] for t in _elder_turns(sid3)] == ["산에 갔어요"]


def test_low_confidence_then_new_answer_and_no_response_drop_pending(client):
    ctx = setup_elder(client)
    sid = _create(client, ctx)["session_id"]
    url = f"/api/elder/sessions/{sid}/turns"
    client.post(url, json={"text": "웅얼", "input_type": "VOICE", "stt_confidence": 0.3})
    r = client.post(url, json={"text": "가족이랑 갔어요", "input_type": "VOICE", "stt_confidence": 0.9}).json()
    assert r["turn_no"] == 2 and [t["text"] for t in _elder_turns(sid)] == ["가족이랑 갔어요"]  # 다른 말 = 새 답

    client.post(url, json={"text": "웅얼", "input_type": "VOICE", "stt_confidence": 0.3})
    client.post(url, json={"input_type": "BUTTON", "event": "NO_RESPONSE"})  # 확인에 답 없음 → 맡긴 문장 버림
    r = client.post(url, json={"text": "네", "input_type": "CHIP"}).json()
    assert [t["text"] for t in _elder_turns(sid)] == ["가족이랑 갔어요", "네"]  # '네'는 보통 답


def test_text_input_and_get_returns_past_turns(client):
    """글로 쓰기(TEXT, D52 ⑤)는 확인 없이 저장되고, GET 은 이어서 할 때 쓸 지난 말을 준다 (D52 ⑥)."""
    ctx = setup_elder(client)
    sid = _create(client, ctx)["session_id"]
    r = client.post(f"/api/elder/sessions/{sid}/turns", json={"text": "손주랑 바다에 갔어요", "input_type": "TEXT"})
    assert r.status_code == 200 and r.json()["turn_no"] == 2
    assert _elder_turns(sid)[-1]["input_type"] == "TEXT"
    too_long = client.post(f"/api/elder/sessions/{sid}/turns", json={"text": "가" * 501, "input_type": "TEXT"})
    assert too_long.status_code == 422

    got = client.get(f"/api/elder/sessions/{sid}").json()
    assert [t["speaker"] for t in got["turns"]] == ["AI", "ELDER", "AI"]
    assert got["turns"][1]["text"] == "손주랑 바다에 갔어요" and got["turns"][-1]["text"] == got["last_ai"]["text"]
    assert set(got["turns"][0]) == {"speaker", "text"}  # 신뢰도·시각 같은 안쪽 칸은 내보내지 않는다
