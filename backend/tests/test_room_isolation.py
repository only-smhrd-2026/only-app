"""주소 표와 실제 라우트를 대조해 다른 가족방의 자료 접근을 막는다 (NFR-DV-004)."""

import uuid

import pytest
from sqlalchemy import select

from app.db import SessionLocal
from app.main import app
from app.models import Notification
from tests.conftest import setup_elder

# 메서드·주소·유효한 본문. 새 자원 주소를 추가할 때 이 표에도 추가한다.
CASES = [
    ("GET", "/rooms/{room_id}/members", None),
    ("PATCH", "/rooms/{room_id}/members/{user_id}", {"nickname": "가족"}),
    ("DELETE", "/rooms/{room_id}/members/{user_id}", None),
    ("POST", "/rooms/{room_id}/invites", {"kind": "FAMILY"}),
    ("GET", "/rooms/{room_id}/invites", None),
    ("DELETE", "/rooms/{room_id}/invites/{kind}", None),
    ("DELETE", "/rooms/{room_id}/device", None),
    ("PATCH", "/rooms/{room_id}/settings", {"elder_name": "어르신"}),
    ("POST", "/rooms/{room_id}/leave", None),
    ("POST", "/rooms/{room_id}/owner", {"user_id": 1}),
    ("GET", "/rooms/{room_id}/photos", None),
    ("POST", "/rooms/{room_id}/photos", "upload"),
    ("PATCH", "/rooms/{room_id}/photos/{photo_id}/correction", {"corrected_activity": "none"}),
    ("PATCH", "/rooms/{room_id}/photos/{photo_id}", {"caption": "몰래"}),
    ("DELETE", "/rooms/{room_id}/photos/{photo_id}", None),
    ("GET", "/rooms/{room_id}/diaries", None),
    ("POST", "/rooms/{room_id}/diaries", {"body": "소식", "mood": "GOOD", "request_id": str(uuid.uuid4())}),
    ("POST", "/rooms/{room_id}/family-diary/ask", {"text": "소식이에요"}),
    ("POST", "/rooms/{room_id}/family-diary/draft", {"text": "소식이에요"}),
    ("GET", "/rooms/{room_id}/weekly", None),
    ("GET", "/rooms/{room_id}/mood-week", None),
    ("GET", "/rooms/{room_id}/alert", None),
    ("GET", "/rooms/{room_id}/care", None),
    ("POST", "/rooms/{room_id}/alerts/{alert_id}/ack", None),
    ("POST", "/rooms/{room_id}/alerts/{alert_id}/missed", None),
    ("PATCH", "/rooms/{room_id}/integration", {"integration_scope": "NONE"}),
    ("GET", "/diaries/{diary_id}", None),
    ("POST", "/diaries/{diary_id}/read", None),
    ("POST", "/diaries/{diary_id}/reaction", {"kind": "HEART", "on": True}),
    ("POST", "/diaries/{diary_id}/reply", {"text": "보고 싶어요"}),
    ("DELETE", "/diaries/{diary_id}/reply", None),
    ("DELETE", "/diaries/{diary_id}", None),
    ("POST", "/elder/diaries/{diary_id}/read", None),
    ("POST", "/elder/diaries/{diary_id}/like", {"on": True}),
    ("POST", "/elder/diaries/{diary_id}/reply-draft", {"transcript": "고맙다"}),
    ("POST", "/elder/diaries/{diary_id}/reply", {"text": "고맙다"}),
    ("GET", "/elder/sessions/{session_id}", None),
    ("POST", "/elder/sessions/{session_id}/turns", {"text": "네", "input_type": "CHIP"}),
    ("POST", "/elder/sessions/{session_id}/end", {"reason": "USER_STOP"}),
    ("POST", "/elder/sessions/{session_id}/draft", None),
    ("POST", "/notifications/{notification_id}/read", None),
]


def resource_routes(routes, prefix=""):
    """FastAPI의 즉시 등록·지연 include_router 양쪽에서 숨긴 주소까지 읽는다."""
    for route in routes:
        if hasattr(route, "original_router"):
            yield from resource_routes(route.original_router.routes, prefix + route.include_context.prefix)
        elif any(
            "{" + name + "}" in getattr(route, "path", "")
            for name in ("room_id", "diary_id", "photo_id", "session_id", "notification_id")
        ):
            for method in route.methods:
                yield method, (prefix + route.path).removeprefix("/api")


def test_every_resource_route_has_an_isolation_case():
    routes = set(resource_routes(app.routes))
    assert routes == {(method, path) for method, path, _ in CASES}


@pytest.mark.parametrize("method,path,body", CASES)
def test_other_family_cannot_access_resource(client, method, path, body):
    from io import BytesIO

    from PIL import Image

    a = setup_elder(client)
    session = client.post(
        "/api/elder/sessions", json={"session_id": str(uuid.uuid4()), "kind": "MEMORY", "pick_id": a["pick"]["pick_id"]}
    )
    assert session.status_code == 201
    diary = client.post(
        f"/api/rooms/{a['room_id']}/diaries",
        json={"request_id": str(uuid.uuid4()), "body": "가족 소식", "mood": "GOOD"},
    )
    assert diary.status_code == 201
    with SessionLocal() as db:
        notice = db.scalar(select(Notification).where(Notification.room_id == a["room_id"]))
        ids = dict(
            room_id=a["room_id"],
            photo_id=a["photo_ids"][0],
            diary_id=diary.json()["diary_id"],
            session_id=session.json()["session_id"],
            notification_id=notice.notification_id,
            user_id=notice.target_user_id,
            kind="FAMILY",
            alert_id=1,
        )
    client.cookies.clear()
    setup_elder(client)
    kwargs = {"json": body} if body is not None else {}
    if body == "upload":
        image = BytesIO()
        Image.new("RGB", (8, 8)).save(image, "JPEG")
        kwargs = {"files": [("files", ("photo.jpg", image.getvalue(), "image/jpeg"))]}
    response = client.request(method, "/api" + path.format(**ids), **kwargs)
    assert response.status_code in (403, 404, 501), response.text
