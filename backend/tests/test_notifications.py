"""알림 공개 범위·최신 순서·첫 읽음 시각을 확인한다."""

from datetime import timedelta

from sqlalchemy import select

from app.config import now_kst
from app.db import SessionLocal
from app.models import Notification, RoomMember
from app.routers import notifications as notifications_api
from tests.conftest import make_room, signup


def _notification(room_id, user_id, sent_at=None, target_type="FAMILY"):
    with SessionLocal() as db:
        notification = Notification(
            room_id=room_id,
            target_type=target_type,
            target_user_id=user_id,
            kind="DIARY_POSTED",
            title="알림 테스트",
            body="알림 본문",
            link_screen="FDIARY_001",
            sent_at=sent_at or now_kst(),
        )
        db.add(notification)
        db.commit()
        return notification.notification_id


def _assert_hidden(client, notification_id):
    response = client.post(f"/api/notifications/{notification_id}/read")
    assert response.status_code == 404, response.text
    assert response.json()["code"] == "NOTIFICATION_NOT_FOUND"


def test_latest_list_and_first_read_time(client, monkeypatch):
    user = signup(client)
    room_id = make_room(client)["room_id"]
    old = _notification(room_id, user["user_id"], now_kst() - timedelta(minutes=10))
    latest = _notification(room_id, user["user_id"])
    response = client.get("/api/notifications")
    assert response.status_code == 200, response.text
    result = response.json()
    assert [n["notification_id"] for n in result["notifications"]] == [latest, old]
    assert result["unread"] == 2
    assert result["notifications"][0] == {
        "notification_id": latest,
        "room_id": room_id,
        "kind": "DIARY_POSTED",
        "title": "알림 테스트",
        "body": "알림 본문",
        "link_screen": "FDIARY_001",
        "sent_at": result["notifications"][0]["sent_at"],
        "read_at": None,
    }
    path = f"/api/notifications/{old}/read"
    assert client.post(path).status_code == 204
    with SessionLocal() as db:
        first_time = db.get(Notification, old).read_at
        assert first_time is not None
    monkeypatch.setattr(notifications_api, "now_kst", lambda: first_time + timedelta(minutes=1))
    response = client.post(path)
    assert response.status_code == 204
    assert response.content == b""
    with SessionLocal() as db:
        assert db.get(Notification, old).read_at == first_time
    result = client.get("/api/notifications").json()
    assert result["unread"] == 1
    assert result["notifications"][1]["read_at"] is not None


def test_other_recipient_and_missing_notification_hidden(client):
    user = signup(client)
    room_id = make_room(client)["room_id"]
    notification_id = _notification(room_id, user["user_id"])
    assert client.post(f"/api/notifications/{notification_id}/read").status_code == 204
    with SessionLocal() as db:
        first_time = db.get(Notification, notification_id).read_at
    # 같은 가족방 구성원이어도 다른 수신자의 알림은 읽지 못한다.
    invite = client.post(f"/api/rooms/{room_id}/invites", json={"kind": "FAMILY"}).json()
    signup(client)
    token = invite["url"].split("#", 1)[1]
    assert client.post("/api/invites/accept", json={"token": token, "relation_tag": "GRANDCHILD"}).status_code == 200
    _assert_hidden(client, notification_id)
    _assert_hidden(client, 999999)
    assert client.get("/api/notifications").json() == {"notifications": [], "unread": 0}
    with SessionLocal() as db:
        assert db.get(Notification, notification_id).read_at == first_time


def test_elder_notifications_hidden(client):
    user = signup(client)
    room_id = make_room(client)["room_id"]
    for recipient in (None, user["user_id"]):
        notification_id = _notification(room_id, recipient, target_type="ELDER")
        _assert_hidden(client, notification_id)
        with SessionLocal() as db:
            assert db.get(Notification, notification_id).read_at is None
    assert client.get("/api/notifications").json() == {"notifications": [], "unread": 0}


def test_login_required(client):
    for response in (client.get("/api/notifications"), client.post("/api/notifications/999999/read")):
        assert response.status_code == 401
        assert response.json()["code"] == "AUTH_REQUIRED"


def test_removed_member_cannot_access_old_notifications(client):
    user = signup(client)
    room_id = make_room(client)["room_id"]
    hidden = _notification(room_id, user["user_id"])
    remaining_room = make_room(client)["room_id"]
    visible = _notification(remaining_room, user["user_id"])
    with SessionLocal() as db:
        member = db.scalar(
            select(RoomMember).where(RoomMember.room_id == room_id, RoomMember.user_id == user["user_id"])
        )
        member.removed_at = now_kst()
        db.commit()
    result = client.get("/api/notifications").json()
    assert [n["notification_id"] for n in result["notifications"]] == [visible]
    assert result["unread"] == 1
    _assert_hidden(client, hidden)
    with SessionLocal() as db:
        assert db.get(Notification, hidden).read_at is None


def test_limit_does_not_limit_unread_and_ties_use_id(client, monkeypatch):
    user = signup(client)
    room_id = make_room(client)["room_id"]
    sent_at = now_kst()
    first = _notification(room_id, user["user_id"], sent_at)
    second = _notification(room_id, user["user_id"], sent_at)
    result = client.get("/api/notifications").json()
    assert [n["notification_id"] for n in result["notifications"]] == [second, first]
    monkeypatch.setattr(notifications_api, "NOTI_LIST_LIMIT", 1)
    result = client.get("/api/notifications").json()
    assert [n["notification_id"] for n in result["notifications"]] == [second]
    assert result["unread"] == 2
