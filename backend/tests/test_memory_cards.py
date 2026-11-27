"""회상 카드 (D115, 11/27 팀 회의) — 회상 대화가 끝나면 가족용 요약이 생기고, 가족 홈 피드·어르신 사진첩에 보인다.

요약 작업(ai/memory_card.run_pending)은 mock AI(가장 긴 답을 따옴)로 돈다. 좋아요·댓글은 일기와 같은 규칙.
"""

import uuid
from datetime import timedelta

from app.ai import memory_card
from app.ai.schemas import MemoryCardText
from app.config import now_kst
from app.db import SessionLocal
from app.models import Photo, TalkSession
from tests.conftest import setup_elder, signup

SAID = "옛날엔 뒷산에 가면 산딸기가 지천이었어"


def _talk(room_id, photo_id, *, private=False, flag="NONE", ended=True, started_ago=timedelta(minutes=5)):
    now = now_kst()
    turns = [
        {"turn_no": 1, "speaker": "AI", "text": "이 사진 보니 무슨 생각 나세요?", "created_at": now.isoformat()},
        {"turn_no": 2, "speaker": "ELDER", "text": SAID, "reply_to_turn_no": 1, "created_at": now.isoformat()},
    ]
    with SessionLocal() as db:
        s = TalkSession(
            session_id=uuid.uuid4(),
            room_id=room_id,
            kind="MEMORY",
            photo_id=photo_id,
            input_mode="VOICE",
            started_at=now - started_ago,
            ended_at=now if ended else None,
            private_flag=private,
            emotion_flag=flag,
            turns=turns,
            turn_count=2,
        )
        db.add(s)
        db.commit()
        return s.session_id


def _run():
    with SessionLocal() as db:
        return memory_card.run_pending(db)


def _summary(session_id):
    with SessionLocal() as db:
        return db.get(TalkSession, session_id).family_summary


def test_card_made_and_shown_in_feed_and_album(client):
    e = setup_elder(client)
    room_id, photo_id = e["room_id"], e["photo_ids"][0]
    sid = _talk(room_id, photo_id)
    _run()
    assert SAID[:10] in _summary(sid)
    (card,) = client.get(f"/api/rooms/{room_id}/memories").json()["memories"]
    assert card["session_id"] == str(sid)
    assert card["photo_url"].startswith("/api/media/")
    assert card["reactions"] == []
    # 어르신 사진첩: 그 사진에 나눈 이야기 (11/27 '할머니 화면에서 회상이 안 보인다')
    photos = {p["photo_id"]: p for p in client.get("/api/elder/album").json()["photos"]}
    assert [t["summary"] for t in photos[photo_id]["talks"]] == [card["summary"]]
    assert photos[e["photo_ids"][1]]["talks"] == []


def test_no_card_for_private_risk_or_unfinished(client):
    e = setup_elder(client)
    room_id, photo_id = e["room_id"], e["photo_ids"][0]
    private = _talk(room_id, photo_id, private=True)
    risk = _talk(room_id, photo_id, flag="RISK")
    open_now = _talk(room_id, photo_id, ended=False)  # 아직 이어 할 수 있는 대화 — 다음 차례에
    left_open = _talk(room_id, photo_id, ended=False, started_ago=timedelta(hours=1))  # 앱을 닫고 둔 대화
    old = _talk(room_id, photo_id, started_ago=timedelta(days=2))  # 하루가 지난 대화는 만들지 않는다
    _run()
    assert (_summary(private), _summary(risk), _summary(open_now), _summary(old)) == ("", "", None, None)
    assert _summary(left_open)
    memories = client.get(f"/api/rooms/{room_id}/memories").json()["memories"]
    assert [c["session_id"] for c in memories] == [str(left_open)]


def test_ai_error_retries_next_run(client, monkeypatch):
    e = setup_elder(client)
    sid = _talk(e["room_id"], e["photo_ids"][0])

    def fail(*_a, **_k):
        raise memory_card.llm.LlmError("장애")

    monkeypatch.setattr(memory_card.llm, "call_json", fail)
    assert _run() == (0, 1)
    assert _summary(sid) is None
    monkeypatch.undo()
    _run()
    assert _summary(sid)


def test_check_falls_back_to_plain_line():
    pairs = [{"said": SAID}]
    ok = MemoryCardText(summary="뒷산 산딸기 이야기를 들려주셨어요.", quote="뒷산에 가면")
    assert memory_card.check(ok, pairs) == ok.summary
    for bad in (
        MemoryCardText(summary="바다에 가셨대요.", quote="바다에 갔어"),  # 하지 않은 말
        MemoryCardText(summary="뒷산 산딸기 이야기를 들려주셨다", quote="뒷산에 가면"),  # 말끝
        MemoryCardText(summary="가" * 130 + "요", quote="뒷산에 가면"),  # 길이
    ):
        assert memory_card.check(bad, pairs) == memory_card.PLAIN


def test_like_and_comments(client):
    e = setup_elder(client)
    sid = _talk(e["room_id"], e["photo_ids"][0])
    _run()
    url = f"/api/memories/{sid}"
    assert client.get(url).json()["session_id"] == str(sid)  # 회상 상세 (11/27)
    r = client.post(f"{url}/reaction", json={"kind": "HEART", "on": True})
    assert r.status_code == 200, r.text
    assert [x["kind"] for x in r.json()["reactions"]] == ["HEART"]
    again = client.post(f"{url}/reaction", json={"kind": "HEART", "on": True})
    assert again.json()["reactions"] == r.json()["reactions"]  # 두 번 눌러도 1칸
    text = ("엄마 " + "산딸기 " * 60)[:200].strip()  # 200자까지 (11/27 — 40자에서 늘림)
    r = client.post(f"{url}/reply", json={"text": text})
    assert r.status_code == 200, r.text
    _, reply = r.json()["reactions"]
    assert (reply["kind"], reply["text"], reply["name"]) == ("REPLY", text, "테스터")
    r = client.patch(f"{url}/reply", json={"at": reply["at"], "text": "보고 싶어요 😊"})
    assert r.json()["reactions"][1]["text"] == "보고 싶어요 😊"
    assert client.delete(f"{url}/reply", params={"at": reply["at"]}).status_code == 204
    assert client.post(f"{url}/reaction", json={"kind": "HEART", "on": False}).json()["reactions"] == []
    assert client.post(f"{url}/reply", json={"text": "가" * 201}).status_code == 422


def test_other_room_and_deleted_photo_are_hidden(client):
    e = setup_elder(client)
    sid = _talk(e["room_id"], e["photo_ids"][0])
    _run()
    signup(client)  # 다른 가족으로 로그인
    assert client.get(f"/api/rooms/{e['room_id']}/memories").status_code == 404
    assert client.post(f"/api/memories/{sid}/reaction", json={"kind": "HEART", "on": True}).status_code == 404
    assert client.get(f"/api/memories/{sid}").status_code == 404
    with SessionLocal() as db:
        db.get(Photo, e["photo_ids"][0]).status = "DELETED"
        db.commit()
    assert client.get("/api/elder/album").status_code == 200  # 어르신 기기 쿠키는 그대로
