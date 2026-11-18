import pytest

from app.config import LOGIN_RATE_PER_MIN
from tests.conftest import signup

PATH = "/api/auth/password"


def test_password_change_replaces_credentials(client):
    user = signup(client)
    result = client.post(PATH, json={"current_password": "test1234", "new_password": "new-test1234"})
    assert result.status_code == 200
    assert "session=" in result.headers["set-cookie"]
    login = "/api/auth/login"
    assert client.post(login, json={"email": user["email"], "password": "test1234"}).status_code == 401
    assert client.post(login, json={"email": user["email"], "password": "new-test1234"}).status_code == 200


@pytest.mark.parametrize(
    ("current", "new", "status", "code"),
    [
        ("wrong", "new-test1234", 400, "WRONG_PASSWORD"),
        ("test1234", "test1234", 400, "SAME_PASSWORD"),
        ("test1234", "1234567", 422, None),
        ("test1234", "가" * 25, 422, None),
    ],
)
def test_password_change_validation(client, current, new, status, code):
    signup(client)
    result = client.post(PATH, json={"current_password": current, "new_password": new})
    assert result.status_code == status
    if code:
        assert result.json()["code"] == code


def test_password_change_requires_login(client):
    assert client.post(PATH, json={"current_password": "test1234", "new_password": "new-test1234"}).status_code == 401


def test_password_change_rate_limit(client):
    signup(client)
    body = {"current_password": "wrong", "new_password": "new-test1234"}
    for _ in range(LOGIN_RATE_PER_MIN):
        assert client.post(PATH, json=body).status_code == 400
    assert client.post(PATH, json=body).status_code == 429
