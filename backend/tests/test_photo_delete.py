"""사진 삭제 권한·미진행 선택 만료·원본 보존을 확인한다."""

from datetime import timedelta

from sqlalchemy import select

from app.config import today_kst
from app.db import SessionLocal
from app.models import DailyPick, Photo, RoomMember
from app.services import storage
from tests.conftest import make_room, signup
from tests.test_photos import _jpeg


def upload(client, room, source="FAMILY"):
    result = client.post(
        f"/api/rooms/{room}/photos", files=[("files", ("sample.jpg", _jpeg(), "image/jpeg"))], data={"source": source}
    )
    assert result.status_code == 201, result.text
    return result.json()["photos"][0]


def test_delete_own_photo_expires_today_and_preserves_file(client):
    signup(client)
    room = make_room(client)["room_id"]
    photo = upload(client, room)
    pid = photo["photo_id"]
    assert photo["is_mine"] is True
    with SessionLocal() as db:
        db.add_all(
            [
                DailyPick(room_id=room, photo_id=pid, pick_date=today_kst()),
                DailyPick(room_id=room, photo_id=pid, pick_date=today_kst() - timedelta(days=1), status="COMPLETED"),
            ]
        )
        db.commit()
    before = next(r for r in client.get("/api/rooms").json() if r["room_id"] == room)["photo_count"]
    assert client.delete(f"/api/rooms/{room}/photos/{pid}").status_code == 204
    assert client.get(f"/api/rooms/{room}/photos").json()["photos"] == []
    assert client.get(photo["url"]).status_code == 404
    assert next(r for r in client.get("/api/rooms").json() if r["room_id"] == room)["photo_count"] == before - 1
    with SessionLocal() as db:
        assert db.get(Photo, pid).status == "DELETED"
        assert storage.get(db.get(Photo, pid).object_key) is not None
        picks = db.scalars(select(DailyPick).where(DailyPick.room_id == room).order_by(DailyPick.pick_date)).all()
        assert [p.status for p in picks] == ["COMPLETED", "EXPIRED"]
    assert client.delete(f"/api/rooms/{room}/photos/{pid}").status_code == 404


def test_photo_permissions_source_and_is_mine(client):
    owner = signup(client)
    room = make_room(client)["room_id"]
    photo = upload(client, room)
    diary = upload(client, room, "FAMILY_DIARY")
    path = f"/api/rooms/{room}/photos/{photo['photo_id']}"
    response = client.delete(f"/api/rooms/{room}/photos/{diary['photo_id']}")
    assert response.status_code == 400
    other = signup(client)
    assert client.delete(path).status_code == 404
    with SessionLocal() as db:
        db.add(RoomMember(room_id=room, user_id=other["user_id"], relation_tag="CHILD"))
        db.commit()
    result = client.delete(path)
    assert result.status_code == 403 and result.json()["code"] == "NOT_UPLOADER"
    assert client.get(f"/api/rooms/{room}/photos").json()["photos"][0]["is_mine"] is False
    others = upload(client, room)
    assert client.patch(path + "/correction", json={"corrected_activity": "산책"}).json()["is_mine"] is False
    client.post("/api/auth/login", json={"email": owner["email"], "password": "test1234"})
    assert client.delete(f"/api/rooms/{room}/photos/{others['photo_id']}").status_code == 204
    client.cookies.clear()
    assert client.delete(path).status_code == 401
