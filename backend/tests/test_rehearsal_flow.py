"""저녁 합친 뒤 다시 돌릴 테스트: 리허설의 가족·어르신 서버 흐름을 처음부터 끝까지 확인한다."""

import uuid
from datetime import timedelta

from app.config import now_kst
from app.db import SessionLocal
from app.services import weekly
from tests.conftest import add_photos, connect_device, make_room, signup


def test_rehearsal_flow(client):
    signup(client)
    room = make_room(client)["room_id"]
    assert len(add_photos(room)) == 3
    assert connect_device(client, room)["room_id"] == room
    home = client.get("/api/elder/home")
    assert home.status_code == 200
    pick = home.json()["today_pick"]
    assert pick["status"] == "PENDING"

    memory = client.post(
        "/api/elder/sessions",
        json={
            "session_id": str(uuid.uuid4()),
            "kind": "MEMORY",
            "pick_id": pick["pick_id"],
        },
    )
    assert memory.status_code == 201
    sid = memory.json()["session_id"]
    for answer in ("가족과 나들이하던 사진이에요", "함께 산책하니 즐거웠어요"):
        turn = client.post(f"/api/elder/sessions/{sid}/turns", json={"text": answer, "input_type": "CHIP"})
        assert turn.status_code == 200
        assert turn.json()["state"] == "CONTINUE"
    ended = client.post(f"/api/elder/sessions/{sid}/end", json={"reason": "USER_STOP"})
    assert ended.status_code == 200
    assert ended.json()["end_reason"] == "USER_STOP"

    diary_session = client.post("/api/elder/sessions", json={"session_id": str(uuid.uuid4()), "kind": "DIARY"})
    assert diary_session.status_code == 201
    did = diary_session.json()["session_id"]
    for answer in ("공원을 걸었어요", "가족과 함께요", "좋았어요"):
        turn = client.post(f"/api/elder/sessions/{did}/turns", json={"text": answer, "input_type": "CHIP"})
        assert turn.status_code == 200
    assert turn.json()["state"] == "ENDED"
    draft = client.post(f"/api/elder/sessions/{did}/draft")
    assert draft.status_code == 200
    assert draft.json()["body"]
    posted = client.post("/api/elder/diaries", json={"session_id": did, "request_id": str(uuid.uuid4())})
    assert posted.status_code == 201
    elder_diary = posted.json()["diary_id"]
    listed = client.get(f"/api/rooms/{room}/diaries")
    assert listed.status_code == 200
    assert elder_diary in [d["diary_id"] for d in listed.json()["diaries"]]

    reaction = client.post(f"/api/diaries/{elder_diary}/reaction", json={"kind": "HEART", "on": True})
    assert reaction.status_code == 200
    assert reaction.json()["reactions"][0]["kind"] == "HEART"
    family = client.post(
        f"/api/rooms/{room}/diaries",
        json={
            "request_id": str(uuid.uuid4()),
            "body": "오늘도 잘 지내고 있어요.",
            "mood": "GOOD",
        },
    )
    assert family.status_code == 201
    family_diary = family.json()["diary_id"]
    news = client.get("/api/elder/family-news")
    assert news.status_code == 200
    assert family_diary in [d["diary_id"] for d in news.json()["diaries"]]
    assert news.json()["hearts"][0]["diary_id"] == elder_diary
    assert client.post(f"/api/elder/diaries/{family_diary}/read").status_code == 204
    heard = client.post("/api/elder/hearts/heard", json={"until": news.json()["hearts"][-1]["at"]})
    assert heard.status_code == 204
    after = client.get("/api/elder/family-news")
    assert after.status_code == 200
    assert after.json() == {"diaries": [], "hearts": []}
    notices = client.get("/api/notifications")
    assert notices.status_code == 200
    assert any(n["kind"] == "DIARY_POSTED" and n["room_id"] == room for n in notices.json()["notifications"])

    # 방금 만든 기록의 주가 마감된 시점으로 집계해 카드의 데이터 연결까지 확인한다.
    completed_week = now_kst() + timedelta(days=7)
    with SessionLocal() as db:
        weekly.build(db, room, completed_week)
    story = client.get(f"/api/rooms/{room}/weekly")
    assert story.status_code == 200
    assert elder_diary in [d["diary_id"] for d in story.json()["diaries"]]
