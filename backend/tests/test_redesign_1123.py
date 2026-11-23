"""11/23 시안 → 앱 옮기기 새 API: 어르신 설정·말로 답하기·'안 받으세요'·알림 끄기·마음 체크 종류·사진첩 칩.

유료 API 는 부르지 않는다(mock). 위로 대화는 test_mood_signal.py, 갤러리 사진은 test_elder_camera.py.
"""

import uuid

from sqlalchemy import func, select

from app.db import SessionLocal
from app.models import Notification, Photo
from tests.conftest import setup_elder
from tests.test_elder_camera import _jpeg
from tests.test_reactions import _diary, _join, _like, _stored


def _count(room_id, kind) -> int:
    with SessionLocal() as db:
        return db.scalar(
            select(func.count())
            .select_from(Notification)
            .where(Notification.room_id == room_id, Notification.kind == kind)
        )


# ---------------------------------------------------------------- 어르신 설정 · 홈
def test_elder_settings_change_only_sent_fields(client):
    setup_elder(client)
    home = client.get("/api/elder/home").json()
    assert (home["diary_today"], home["mood_due"]) == (False, False)  # 오늘의 한 장이 아직 기다리는 중
    r = client.patch("/api/elder/settings", json={"font_size": "XXL", "tts_speed": 0.9})
    assert r.status_code == 200, r.text
    assert r.json() == home["settings"] | {"font_size": "XXL", "tts_speed": "0.90"}
    assert client.get("/api/elder/home").json()["settings"] == r.json()
    assert client.patch("/api/elder/settings", json={"tts_voice": "CHILD"}).status_code == 422
    client.cookies.delete("device")
    assert client.patch("/api/elder/settings", json={"font_size": "L"}).status_code == 401


# ---------------------------------------------------------------- 어르신 [말로 답하기]
def test_elder_reply_on_family_diary(client):
    room_id = setup_elder(client)["room_id"]
    owner = client.get("/api/auth/me").json()["user_id"]
    family = _diary(room_id, "FAMILY")
    said = "어 그래 잘 다녀왔다니 참 좋구나 다음에는 할머니랑 같이 가자 맛있는 것도 먹고"
    draft = client.post(f"/api/elder/diaries/{family}/reply-draft", json={"transcript": said})
    assert draft.status_code == 200 and draft.json() == {"text": said[:40]}  # mock → 하신 말 앞 40자
    assert _like(client, family).status_code == 200
    r = client.post(f"/api/elder/diaries/{family}/reply", json={"text": "좋구나, 다음엔 같이 가자"})
    assert r.status_code == 200, r.text
    assert [(x["by"], x["kind"], x.get("text")) for x in r.json()["reactions"]] == [
        ("ELDER", "LIKE", None),
        ("ELDER", "REPLY", "좋구나, 다음엔 같이 가자"),
    ]
    client.post(f"/api/elder/diaries/{family}/reply", json={"text": "좋구나, 다음엔 같이 가자"})  # 두 번 누름
    assert _count(room_id, "ELDER_REPLY") == 1
    with SessionLocal() as db:
        note = db.scalar(select(Notification).where(Notification.kind == "ELDER_REPLY"))
        assert (note.target_user_id, note.link_screen, note.link_id) == (owner, "HOME_002", family)
    client.post(f"/api/elder/diaries/{family}/reply", json={"text": "고맙다"})  # 새로 보내면 그 한 칸이 바뀐다
    assert _count(room_id, "ELDER_REPLY") == 2
    assert _like(client, family, on=False).status_code == 200  # 좋아요를 꺼도 답은 남는다
    assert [(x["kind"], x.get("text")) for x in _stored(family)] == [("REPLY", "고맙다")]
    elder = _diary(room_id)
    assert client.post(f"/api/elder/diaries/{elder}/reply", json={"text": "고맙다"}).status_code == 409
    assert client.post(f"/api/elder/diaries/{family}/reply", json={"text": "가" * 41}).status_code == 422


# ---------------------------------------------------------------- 급한 알림 '안 받으세요'
def test_missed_call_tells_other_family(client):
    room_id = setup_elder(client)["room_id"]
    _join(client, room_id)  # 이제 '손주'로 로그인
    nine = [0] * 8 + [1]  # PHQ-9 9번 > 0 → 급한 알림 (MOOD)
    saved = client.post("/api/elder/mood-check", json={"kind": "PHQ9", "answers": nine}).json()
    assert "가족" not in saved["say"] and _count(room_id, "MOOD_URGENT") == 2
    alert_id = client.get(f"/api/rooms/{room_id}/alert").json()["alert_id"]
    r = client.post(f"/api/rooms/{room_id}/alerts/{alert_id}/missed")
    assert r.status_code == 200, r.text
    assert (r.json()["missed_by_name"], r.json()["acked_at"]) == ("손주", None)  # 카드는 확인 안 된 채
    client.post(f"/api/rooms/{room_id}/alerts/{alert_id}/missed")  # 두 번 누름
    assert _count(room_id, "URGENT_MISSED") == 1  # 누른 사람 빼고 방장 1명에게 1번


# ---------------------------------------------------------------- 알림 종류별 끄기
def test_push_prefs(client):
    setup_elder(client)
    assert client.get("/api/push/prefs").json() == {"muted": []}
    r = client.put("/api/push/prefs", json={"muted": ["WEEKLY", "DIARY", "DIARY"]})
    assert r.status_code == 200 and r.json() == {"muted": ["DIARY", "WEEKLY"]}
    assert client.get("/api/push/prefs").json() == {"muted": ["DIARY", "WEEKLY"]}
    assert client.put("/api/push/prefs", json={"muted": ["URGENT"]}).status_code == 422  # 급한 알림은 못 끈다


# ---------------------------------------------------------------- 마음 체크 종류 · 지난 결과
def test_mood_kinds_and_history(client):
    room_id = setup_elder(client)["room_id"]
    assert client.post("/api/elder/mood-check", json={"kind": "GAD7", "answers": [0] * 8}).status_code == 422
    assert client.post("/api/elder/mood-check", json={"kind": "UCLA3", "answers": [3, 0, 0]}).status_code == 422
    gad = client.post("/api/elder/mood-check", json={"kind": "GAD7", "answers": [3] * 7}).json()
    assert (gad["face"], gad["title"]) == ("😟", "요즘 걱정이 많으셨군요")
    assert client.post("/api/elder/mood-check", json={"kind": "MEMGAME", "answers": [3]}).status_code == 200
    items = client.get("/api/elder/mood-history").json()["items"]
    assert {i["kind"] for i in items} == {"GAD7", "MEMGAME"} and all("total" not in i for i in items)
    # 걱정·놀이는 가족 마음 카드에 나오지 않고 급한 알림도 없다
    assert client.get(f"/api/rooms/{room_id}/mood-week").json()["last_check"] is None
    assert _count(room_id, "MOOD_URGENT") == 0 and _count(room_id, "MOOD_LOW_2D") == 0


# ---------------------------------------------------------------- 가족 사진첩 칩 · 남은 사진
def test_family_photos_group_uploader_shown_waiting(client):
    ctx = setup_elder(client)
    room_id, pick = ctx["room_id"], ctx["pick"]
    with SessionLocal() as db:
        db.get(Photo, ctx["photo_ids"][0]).activity = "김장"
        db.commit()
    gallery = client.post(
        "/api/elder/album",
        files=[("file", ("g.jpg", _jpeg(), "image/jpeg"))],
        data={"request_id": str(uuid.uuid4())},
    ).json()
    out = client.get(f"/api/rooms/{room_id}/photos").json()
    by_id = {p["photo_id"]: p for p in out["photos"]}
    assert by_id[gallery["photo_id"]]["uploader_name"] == "순자 할머니"  # 어르신 사진 (11/23 사진첩에 들어감)
    assert by_id[ctx["photo_ids"][0]]["group"] == "FOOD"
    assert out["waiting_count"] == 2  # 오늘의 한 장으로 나온 1장 빼고
    assert not any(p["shown"] for p in out["photos"])  # 오늘의 한 장이 아직 기다리는 중
    client.post(
        "/api/elder/sessions", json={"session_id": str(uuid.uuid4()), "kind": "MEMORY", "pick_id": pick["pick_id"]}
    )
    shown = [p["photo_id"] for p in client.get(f"/api/rooms/{room_id}/photos").json()["photos"] if p["shown"]]
    assert shown == [pick["photo_id"]]
    food = client.get(f"/api/rooms/{room_id}/photos", params={"group": "FOOD"}).json()["photos"]
    assert [p["photo_id"] for p in food] == [ctx["photo_ids"][0]]
    assert client.get(f"/api/rooms/{room_id}/photos", params={"group": "PETS"}).status_code == 422


# ---------------------------------------------------------------- 초대 링크의 초대한 사람
def test_invite_status_names_inviter(client):
    room_id = setup_elder(client)["room_id"]
    token = client.post(f"/api/rooms/{room_id}/invites", json={"kind": "FAMILY"}).json()["url"].split("#", 1)[1]
    assert client.post("/api/invites/status", json={"token": token}).json()["inviter_name"] == "테스터"


def test_family_sees_other_checks_as_result_only(client):
    """외로움·걱정·기억력 체크·기억력 놀이는 가족 홈에 마지막 결과(얼굴·말)만 — 점수·알림 없음 (11/23 사용자)."""
    room_id = setup_elder(client)["room_id"]
    for kind, answers in (("UCLA3", [2, 2, 2]), ("GAD7", [3] * 7), ("SMCQ", [1] * 14), ("MEMGAME", [0])):
        assert client.post("/api/elder/mood-check", json={"kind": kind, "answers": answers}).status_code == 200
    week = client.get(f"/api/rooms/{room_id}/mood-week").json()
    assert week["last_check"] is None and _count(room_id, "MOOD_LOW_2D") == 0
    others = week["other_checks"]
    assert [o["kind"] for o in others] == ["UCLA3", "GAD7", "SMCQ", "MEMGAME"]
    assert all(set(o) == {"kind", "check_date", "face", "title"} for o in others)  # 점수·답 없음
    assert others[0]["title"] == "요즘 많이 쓸쓸하셨군요"
    client.post("/api/elder/mood-check", json={"kind": "PHQ8", "answers": [3] * 8})
    week = client.get(f"/api/rooms/{room_id}/mood-week").json()
    assert week["last_check"]["level"] == "HARD" and _count(room_id, "MOOD_LOW_2D") == 1
