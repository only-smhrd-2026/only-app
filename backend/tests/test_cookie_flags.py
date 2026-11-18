from http.cookies import SimpleCookie

from fastapi import Response

from app.config import DEVICE_COOKIE_DAYS, SESSION_COOKIE_DAYS, settings
from app.security import DEVICE_COOKIE, SESSION_COOKIE, set_cookie
from tests.conftest import add_photos, make_room


def _assert_cookie(response, name, max_age, *, secure=False):
    cookie = SimpleCookie(response.headers["set-cookie"])[name]
    assert cookie["httponly"] is True
    assert cookie["samesite"].lower() == "lax"
    assert cookie["path"] == "/"
    assert int(cookie["max-age"]) == max_age
    assert bool(cookie["secure"]) is secure


def test_family_and_device_cookie_flags(client):
    signup = client.post(
        "/api/auth/signup",
        json={"email": "cookie-flags@test.local", "password": "test1234", "name": "테스터", "terms_agreed": True},
    )
    _assert_cookie(signup, SESSION_COOKIE, SESSION_COOKIE_DAYS * 86400)
    login = client.post("/api/auth/login", json={"email": "cookie-flags@test.local", "password": "test1234"})
    _assert_cookie(login, SESSION_COOKIE, SESSION_COOKIE_DAYS * 86400)
    room = make_room(client)["room_id"]
    add_photos(room)
    invite = client.post(f"/api/rooms/{room}/invites", json={"kind": "ELDER_DEVICE"})
    token = invite.json()["url"].split("#", 1)[1]
    connected = client.post("/api/devices/connect", json={"token": token})
    _assert_cookie(connected, DEVICE_COOKIE, DEVICE_COOKIE_DAYS * 86400)
    _assert_cookie(client.post("/api/auth/logout"), SESSION_COOKIE, 0)


def test_deploy_cookie_flags(monkeypatch):
    monkeypatch.setattr(settings, "APP_ENV", "deploy")
    for name, days in ((SESSION_COOKIE, SESSION_COOKIE_DAYS), (DEVICE_COOKIE, DEVICE_COOKIE_DAYS)):
        response = Response()
        set_cookie(response, name, "test-value", days)
        _assert_cookie(response, name, days * 86400, secure=True)
