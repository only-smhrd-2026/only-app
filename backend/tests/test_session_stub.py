"""세션 API 계약 — 8턴째 ENDED, 저신뢰 확인 질문·잠금, 무응답 3단계 (초석 D 완료 기준)."""

import uuid
from datetime import timedelta

from sqlalchemy import func, select

from app.config import now_kst
from app.db import SessionLocal
from app.models import Notification, SessionTurn, TalkSession
from tests.conftest import setup_elder


def _create(client, ctx, kind="MEMORY"):
    body = {"session_id": str(uuid.uuid4()), "kind": kind, "pick_id": ctx["pick"]["pick_id"]}
    r = client.post("/api/elder/sessions", json=body)
    assert r.status_code == 201, r.text
    return r.json()


def test_eight_turns_then_ended(client):
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

    for i in range(7):
        r = client.post(f"/api/elder/sessions/{sid}/turns", json={"text": "네, 기억나요", "input_type": "CHIP"}).json()
        assert r["state"] == "CONTINUE" and r["turn_no"] == i + 2, r

    last = client.post(
        f"/api/elder/sessions/{sid}/turns", json={"text": "네", "input_type": "VOICE", "stt_confidence": 0.9}
    )
    body = last.json()
    assert body["state"] == "ENDED" and body["end_reason"] == "COMPLETED" and body["turn_no"] == 8
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
        turns = db.scalars(
            select(SessionTurn).where(SessionTurn.session_id == s.session_id).order_by(SessionTurn.turn_no)
        ).all()
        assert len(gaps) == len(turns) + 1
        t = now_kst() - timedelta(seconds=sum(gaps))
        s.started_at = t
        for turn, gap in zip(turns, gaps):
            t += timedelta(seconds=gap)
            turn.created_at = t
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
        texts = db.scalars(
            select(SessionTurn.text).where(SessionTurn.session_id == uuid.UUID(sid)).order_by(SessionTurn.turn_no)
        ).all()
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
