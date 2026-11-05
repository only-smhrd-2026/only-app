"""세션 API 계약 — 8턴째 ENDED, 저신뢰 확인 질문·잠금, 무응답 3단계 (초석 D 완료 기준)."""

import uuid

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
