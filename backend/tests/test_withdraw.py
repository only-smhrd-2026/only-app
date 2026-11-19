"""회원 탈퇴: 계정은 바로 익명으로, 글·사진은 '탈퇴한 가족' 이름으로 남는다. 방장인 방은 넘기거나 혼자면 다 지운다."""

import logging
import uuid
from datetime import timedelta

from sqlalchemy import func, select

from app.config import LOGIN_FAIL_PER_EMAIL, LOGIN_RATE_PER_MIN, now_kst, today_kst
from app.db import SessionLocal
from app.models import (
    Base,
    CareDay,
    DailyPick,
    Diary,
    FamilyRoom,
    GroupVocab,
    MoodCheck,
    Notification,
    Photo,
    PushSubscription,
    RoomMember,
    StoryFact,
    TalkSession,
    UrgentAlert,
    User,
    WeeklySummary,
)
from app.routers import account
from app.services import storage
from tests.conftest import add_photos, connect_device, make_room, setup_elder, signup
from tests.test_family_diary import _post
from tests.test_family_news import _diary
from tests.test_member_nickname import login
from tests.test_notifications import _notification
from tests.test_photo_delete import upload
from tests.test_room_settings import family as family

PATH = "/api/auth/withdraw"
# room_id 칸이 있는 표 전부(family_rooms 포함). 표가 늘면 _fill_room 에 줄을 넣어야 아래 '지우기 전 1줄 이상'을 통과한다
ROOM_TABLES = [t for t in Base.metadata.tables.values() if "room_id" in t.c]


def _withdraw(client, transfers=(), password="test1234"):
    return client.post(PATH, json={"password": password, "transfers": list(transfers)})


def _entry(room_id, new_owner):
    return {"room_id": room_id, "new_owner_user_id": new_owner}


def _room_rows(room_id) -> dict[str, int]:
    with SessionLocal() as db:
        return {
            t.name: db.scalar(select(func.count()).select_from(t).where(t.c.room_id == room_id)) for t in ROOM_TABLES
        }


def _fill_room(room_id, user_id) -> list[str]:
    """가족방을 가리키는 모든 표에 줄을 넣는다(서로 가리키는 daily_picks ↔ sessions 포함). 반환: 저장소 파일 key."""
    batch, yesterday = uuid.uuid4(), today_kst() - timedelta(days=1)
    key, thumb = f"rooms/{room_id}/{batch}/0.jpg", f"rooms/{room_id}/{batch}/1.jpg"
    with SessionLocal() as db:
        photo = Photo(
            room_id=room_id,
            uploaded_by=user_id,
            upload_batch_id=batch,
            object_key=key,
            thumb_key=thumb,
            source="FAMILY",
        )
        db.add(photo)
        db.flush()
        pick = DailyPick(room_id=room_id, pick_date=yesterday, photo_id=photo.photo_id, status="COMPLETED")
        db.add(pick)
        db.flush()
        memory = TalkSession(
            session_id=uuid.uuid4(),
            room_id=room_id,
            kind="MEMORY",
            pick_id=pick.pick_id,
            photo_id=photo.photo_id,
            input_mode="VOICE",
        )
        posted, unposted = (
            TalkSession(session_id=uuid.uuid4(), room_id=room_id, kind="DIARY", input_mode="VOICE") for _ in range(2)
        )
        db.add_all([memory, posted, unposted])
        db.flush()
        pick.completed_session_id = memory.session_id
        drawing = f"rooms/{room_id}/{posted.session_id}.jpg"
        draft_drawing = f"rooms/{room_id}/{unposted.session_id}.jpg"  # 올리지 않은 초안의 그림 — 줄은 없고 파일만 있다
        # 11/19 에 생긴 표 3개 — 위급 알림(대화·확인한 가족을 가리킨다)·돌봄 일지·어르신 기기의 푸시 구독
        endpoint = f"https://fcm.googleapis.com/fcm/send/room-{room_id}"
        db.add_all(
            [
                UrgentAlert(room_id=room_id, session_id=memory.session_id, kind="MOOD", acked_by=user_id),
                CareDay(room_id=room_id, care_date=yesterday, level="WATCH"),
                PushSubscription(room_id=room_id, endpoint=endpoint, p256dh="p", auth="a"),
            ]
        )
        diary = {"room_id": room_id, "body": "오늘 공원을 걸었어요.", "mood": "GOOD"}
        db.add_all(
            [
                StoryFact(
                    room_id=room_id,
                    session_id=memory.session_id,
                    source_turn_no=2,
                    fact_text="공원에 다녀옴",
                    kind="EVENT",
                    fact_date=yesterday,
                    expires_at=now_kst() + timedelta(days=30),
                ),
                Diary(
                    **diary,
                    author_type="ELDER",
                    session_id=posted.session_id,
                    illustration_type="AI_DRAWING",
                    illustration_key=drawing,
                    request_id=uuid.uuid4(),
                ),
                Diary(
                    **diary,
                    author_type="FAMILY",
                    author_user_id=user_id,
                    photo_id=photo.photo_id,
                    illustration_type="PHOTO",
                    request_id=uuid.uuid4(),
                ),
                WeeklySummary(
                    room_id=room_id,
                    week_start=yesterday,
                    memory_days=1,
                    diary_days=1,
                    qa_list=[],
                    recall_check={},
                    mood_trend=[],
                    talk_volume={},
                    diaries=[],
                    rule_check_passed=True,
                    model_version="test",
                ),
                Notification(room_id=room_id, target_type="ELDER", kind="MEMORY_REMINDER", title="알림 테스트"),
                MoodCheck(room_id=room_id, check_date=yesterday, answers=[0] * 8, total=0, level="USUAL"),
                GroupVocab(room_id=room_id, term="순자", kind="NAME", source="MEMBER"),
            ]
        )
        db.commit()
    keys = [key, thumb, drawing, draft_drawing]
    for k in keys:
        storage.put(k, b"\xff\xd8\xff\xd9")
    return keys


def test_member_withdraw_wipes_account_but_keeps_posts_as_withdrawn_family(client, family):
    owner, member, room, _ = family
    login(client, owner)
    path = f"/api/rooms/{room}/members/{member['user_id']}"
    assert client.patch(path, json={"nickname": "큰딸"}).status_code == 200
    login(client, member)
    diary = _post(client, room).json()["diary_id"]
    photo = upload(client, room)["photo_id"]
    elder_diary = _diary(room, "ELDER")
    assert client.post(f"/api/diaries/{elder_diary}/reaction", json={"kind": "HEART", "on": True}).status_code == 200
    mine, others = _notification(room, member["user_id"]), _notification(room, owner["user_id"])
    old_cookie = client.cookies.get("session")

    result = _withdraw(client)
    assert result.status_code == 200 and result.json() == {"ok": True}
    assert client.cookies.get("session") is None  # 응답이 로그인 쿠키를 지운다
    client.cookies.set("session", old_cookie)  # 이미 발급된 쿠키(다른 기기)도 막힌다
    assert client.get("/api/auth/me").status_code == 401
    assert _withdraw(client).status_code == 401  # 두 번 눌러도 같다
    stale = client.post("/api/auth/login", json={"email": member["email"], "password": "test1234"})
    assert stale.status_code == 401 and stale.json()["code"] == "LOGIN_FAILED"
    with SessionLocal() as db:
        gone = db.get(User, member["user_id"])
        assert (gone.status, gone.name) == ("WITHDRAWN", "탈퇴한 가족")
        assert (gone.email, gone.password_hash, gone.kakao_id, gone.profile_key) == (None, None, None, None)
        assert db.scalar(select(func.count()).select_from(RoomMember).where(RoomMember.user_id == gone.user_id)) == 0
        assert db.get(Notification, mine) is None  # 그 사람에게 온 알림은 지우고
        assert db.get(Notification, others) is not None  # 다른 가족 알림은 그대로

    login(client, owner)
    kept = client.get(f"/api/diaries/{diary}").json()  # 일기 상세
    assert (kept["author_name"], kept["author_nickname"], kept["is_mine"]) == ("탈퇴한 가족", None, False)
    listed = {d["diary_id"]: d for d in client.get(f"/api/rooms/{room}/diaries").json()["diaries"]}  # 가족 홈
    assert listed[diary]["author_name"] == "탈퇴한 가족"
    assert [r["kind"] for r in listed[elder_diary]["reactions"]] == ["HEART"]  # 보낸 하트도 남는다
    photos = client.get(f"/api/rooms/{room}/photos").json()["photos"]  # 올린 사진
    assert [(p["photo_id"], p["is_mine"]) for p in photos] == [(photo, False)]
    assert [m["user_id"] for m in client.get(f"/api/rooms/{room}/members").json()] == [owner["user_id"]]
    add_photos(room)
    connect_device(client, room)
    news = client.get("/api/elder/family-news").json()  # 어르신 가족 소식
    assert [(d["author_name"], d["author_nickname"]) for d in news["diaries"]] == [("탈퇴한 가족", None)]
    # 하트를 보낸 사람 이름은 없다 — 가족방을 나간 사람과 같다(test_room_leave). 어르신 화면은 '가족이 하트를 보냈어요'
    assert [(h["kind"], h["name"]) for h in news["hearts"]] == [("HEART", None)]


def test_owner_hands_room_over_to_another_family(client, family):
    owner, member, room, _ = family
    login(client, owner)
    for transfers in ([], [_entry(room, None)], [_entry(room, owner["user_id"])], [_entry(room, 2**40)]):
        refused = _withdraw(client, transfers)
        assert refused.status_code == 400 and refused.json()["code"] == "OWNER_TRANSFER_REQUIRED", refused.text
        assert "순자 할머니네 가족방" in refused.json()["detail"]  # 어느 방인지
    assert client.get("/api/auth/me").status_code == 200  # 거절이면 아무것도 안 바뀐다
    assert _withdraw(client, [_entry(room, member["user_id"])]).status_code == 200

    login(client, member)
    (kept,) = client.get("/api/rooms").json()
    assert (kept["room_id"], kept["owner_user_id"], kept["is_owner"], kept["member_count"]) == (
        room,
        member["user_id"],
        True,
        1,
    )
    members = client.get(f"/api/rooms/{room}/members").json()
    assert [(m["user_id"], m["is_owner"]) for m in members] == [(member["user_id"], True)]
    # 방장만 하는 일을 할 수 있다
    assert client.patch(f"/api/rooms/{room}/settings", json={"font_size": "L"}).status_code == 200


def test_owner_alone_deletes_room_with_everything_and_cuts_elder_device(client):
    room = setup_elder(client)["room_id"]
    me = client.get("/api/auth/me").json()
    keys = _fill_room(room, me["user_id"])
    with SessionLocal() as db:
        keys += db.scalars(select(Photo.object_key).where(Photo.room_id == room)).all()
    before = _room_rows(room)
    assert all(before.values()), before  # 모든 표에 지울 줄이 있다
    assert all(storage.get(k) for k in keys)

    for transfers in ([], [_entry(room, 2**40)]):  # 화면이 '지워져요'를 보여 주지 않았으면 지우지 않는다
        refused = _withdraw(client, transfers)
        assert refused.status_code == 400 and refused.json()["code"] == "ROOM_DELETE_CONFIRM_REQUIRED", refused.text
    assert _room_rows(room) == before
    assert _withdraw(client, [_entry(room, None)]).status_code == 200

    after = _room_rows(room)
    assert not any(after.values()), after
    assert [k for k in keys if storage.get(k) is not None] == []
    home = client.get("/api/elder/home")  # 기기 쿠키는 그대로 있지만 가족방이 없다
    assert home.status_code == 401 and home.json()["code"] == "DEVICE_REQUIRED"
    with SessionLocal() as db:
        assert db.get(User, me["user_id"]).status == "WITHDRAWN"


def test_kicked_member_is_not_another_family(client, family):
    owner, member, room, _ = family
    _post(client, room)  # 내보내진 가족이 쓴 일기도 방과 같이 지워진다
    login(client, owner)
    assert client.delete(f"/api/rooms/{room}/members/{member['user_id']}").status_code == 200
    refused = _withdraw(client, [_entry(room, member["user_id"])])
    assert refused.status_code == 400 and refused.json()["code"] == "ROOM_DELETE_CONFIRM_REQUIRED"
    assert _withdraw(client, [_entry(room, None)]).status_code == 200
    assert not any(_room_rows(room).values())
    login(client, member)
    assert client.get("/api/rooms").json() == []


def test_mixed_rooms(client):
    """한 사람이 방 넷에: 혼자 방장(지움) · 다른 가족 있는 방장(넘김) · 구성원(나감) · 내보내진 구성원(줄만 지움)."""
    other = signup(client)
    joined, kicked = make_room(client)["room_id"], make_room(client)["room_id"]
    tokens = [
        client.post(f"/api/rooms/{r}/invites", json={"kind": "FAMILY"}).json()["url"].split("#", 1)[1]
        for r in (joined, kicked)
    ]
    me = signup(client)
    for token in tokens:
        assert client.post("/api/invites/accept", json={"token": token, "relation_tag": "CHILD"}).status_code == 200
    alone, shared = make_room(client)["room_id"], make_room(client)["room_id"]
    token = client.post(f"/api/rooms/{shared}/invites", json={"kind": "FAMILY"}).json()["url"].split("#", 1)[1]
    login(client, other)
    assert client.post("/api/invites/accept", json={"token": token, "relation_tag": "CHILD"}).status_code == 200
    assert client.delete(f"/api/rooms/{kicked}/members/{me['user_id']}").status_code == 200
    login(client, me)
    add_photos(alone, 1)
    with SessionLocal() as db:
        key = db.scalar(select(Photo.object_key).where(Photo.room_id == alone))

    # 한 방이라도 거절이면 아무것도 바뀌지 않는다 — 번호가 앞이라 먼저 지우던 방(alone)도 그대로
    refused = _withdraw(client, [_entry(alone, None)])
    assert refused.status_code == 400 and refused.json()["code"] == "OWNER_TRANSFER_REQUIRED"
    assert all(_room_rows(alone)[t] for t in ("family_rooms", "room_members", "photos"))
    assert storage.get(key) is not None

    result = _withdraw(
        client, [_entry(alone, None), _entry(shared, other["user_id"]), _entry(joined, other["user_id"])]
    )
    assert result.status_code == 200, result.text
    assert storage.get(key) is None
    with SessionLocal() as db:
        assert db.get(FamilyRoom, alone) is None
        owners = {r: db.get(FamilyRoom, r).owner_user_id for r in (shared, joined, kicked)}
        assert owners == dict.fromkeys((shared, joined, kicked), other["user_id"])
        assert db.scalar(select(func.count()).select_from(RoomMember).where(RoomMember.user_id == me["user_id"])) == 0
    login(client, other)
    rooms = {r["room_id"]: (r["is_owner"], r["member_count"]) for r in client.get("/api/rooms").json()}
    assert rooms == dict.fromkeys((joined, kicked, shared), (True, 1))


def test_wrong_password_and_ip_limit(client):
    signup(client)
    for _ in range(LOGIN_RATE_PER_MIN):
        wrong = _withdraw(client, password="wrong")
        assert wrong.status_code == 400 and wrong.json()["code"] == "WRONG_PASSWORD"
    blocked = _withdraw(client)
    assert blocked.status_code == 429 and blocked.json()["code"] == "TOO_MANY_ATTEMPTS"
    assert client.get("/api/auth/me").status_code == 200


def test_wrong_passwords_lock_account_like_login(client, monkeypatch):
    monkeypatch.setattr(account, "login_allowed", lambda ip: True)
    signup(client)
    for _ in range(LOGIN_FAIL_PER_EMAIL):
        assert _withdraw(client, password="wrong").status_code == 400
    locked = _withdraw(client)  # 맞는 비밀번호여도 잠겨 있다 (로그인·비밀번호 바꾸기와 같은 횟수)
    assert locked.status_code == 429 and locked.json()["code"] == "TOO_MANY_ATTEMPTS"
    assert client.get("/api/auth/me").status_code == 200


def test_same_email_signs_up_again_as_new_account(client, monkeypatch):
    monkeypatch.setattr(account, "login_allowed", lambda ip: True)
    user = signup(client)
    for _ in range(LOGIN_FAIL_PER_EMAIL - 1):
        assert _withdraw(client, password="wrong").status_code == 400
    assert _withdraw(client).status_code == 200
    again = signup(client, user["email"])
    assert again["user_id"] != user["user_id"]
    assert client.get("/api/rooms").json() == []
    assert _withdraw(client, password="wrong").status_code == 400
    login(client, again)  # 200 — 옛 계정의 틀린 횟수 9번을 물려받았으면 지금 10번이라 429


def test_storage_failure_does_not_undo_withdraw(client, monkeypatch, caplog):
    signup(client)
    room = make_room(client)["room_id"]
    add_photos(room, 2)
    room_when_deleting = []

    def fail(key):
        with SessionLocal() as db:
            room_when_deleting.append(db.get(FamilyRoom, room))
        raise RuntimeError("비밀 저장소 키")

    monkeypatch.setattr(storage, "delete", fail)
    caplog.set_level(logging.INFO, logger="app.account")
    assert _withdraw(client, [_entry(room, None)]).status_code == 200
    assert client.get("/api/auth/me").status_code == 401
    assert room_when_deleting == [None, None]  # 파일을 지울 때는 DB 저장이 이미 끝나 있다
    (line,) = [r.getMessage() for r in caplog.records if r.name == "app.account"]
    assert line.endswith("rooms_deleted=1 files=2 failed=2")  # 로그에는 개수만 (D15)
    assert "비밀" not in caplog.text


def test_withdraw_requires_login(client):
    assert _withdraw(client).status_code == 401


def test_kakao_member_withdraws_without_password_and_push_subscription_goes(client):
    """카카오로 가입한 회원은 비밀번호가 없다 — 비밀번호 없이 탈퇴하고, 그 사람 폰의 푸시 구독도 지운다 (11/19 통합)."""
    me = signup(client)
    with SessionLocal() as db:
        user = db.get(User, me["user_id"])
        user.login_type, user.kakao_id, user.email, user.password_hash = "KAKAO", "4242", None, None
        endpoint = "https://fcm.googleapis.com/fcm/send/kakao-member"
        db.add(PushSubscription(user_id=user.user_id, endpoint=endpoint, p256dh="p", auth="a"))
        db.commit()
    assert client.post("/api/auth/withdraw", json={"transfers": []}).status_code == 200
    with SessionLocal() as db:
        user = db.get(User, me["user_id"])
        assert (user.status, user.kakao_id) == ("WITHDRAWN", None)
        assert db.scalar(select(func.count()).select_from(PushSubscription)) == 0
    assert client.get("/api/auth/me").status_code == 401
