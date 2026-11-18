import logging
import re

from app import main
from app.deps import current_user
from tests.conftest import make_room, signup


def test_request_timing_logs_only_route_template(client, caplog):
    caplog.set_level(logging.INFO, logger="app.req")
    assert client.get("/api/auth/me").status_code == 401
    user = signup(client)
    assert client.post("/api/auth/login", json={"email": user["email"], "password": "test1234"}).status_code == 200
    room = make_room(client)["room_id"]
    assert client.get(f"/api/rooms/{room}/photos?token=secret-timing-token").status_code == 200
    assert client.get("/unknown-secret-timing-token").status_code == 404
    assert client.get("/api/health").status_code == 200

    records = [r.getMessage() for r in caplog.records if r.name == "app.req"]
    for method, route, status in (
        ("GET", "/api/auth/me", 401),
        ("POST", "/api/auth/login", 200),
        ("GET", "/api/rooms/{room_id}/photos", 200),
        ("GET", "-", 404),
    ):
        prefix = f"req method={method} route={route} status={status} ms="
        assert any(re.fullmatch(re.escape(prefix) + r"\d+", message) for message in records)
    assert all("secret-timing-token" not in message and "/api/health" not in message for message in records)
    assert all(f"/api/rooms/{room}/" not in message for message in records)


def test_timing_logs_handled_server_error(client, caplog, monkeypatch):
    def fail():
        raise RuntimeError("secret failure")

    monkeypatch.setitem(main.app.dependency_overrides, current_user, fail)
    caplog.set_level(logging.INFO, logger="app.req")
    assert client.get("/api/auth/me").status_code == 500
    assert any(r.name == "app.req" and "route=/api/auth/me status=500 ms=" in r.getMessage() for r in caplog.records)
