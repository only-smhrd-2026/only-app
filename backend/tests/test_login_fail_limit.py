from app import security
from app.config import LOGIN_FAIL_PER_EMAIL, LOGIN_FAIL_WINDOW_SEC
from app.routers import auth
from tests.conftest import signup


def test_account_limit_is_case_insensitive_and_expires(client, monkeypatch):
    current = 1000
    monkeypatch.setattr(security, "monotonic", lambda: current)
    monkeypatch.setattr(auth, "login_allowed", lambda ip: True)
    email = signup(client)["email"]
    other = signup(client)["email"]

    def login(address, password):
        return client.post("/api/auth/login", json={"email": address, "password": password})

    for _ in range(LOGIN_FAIL_PER_EMAIL):
        assert login(email.upper(), "wrong").status_code == 401
        assert login("missing@test.local", "wrong").status_code == 401
    blocked = login(email, "test1234")
    assert blocked.status_code == 429 and blocked.json()["code"] == "TOO_MANY_ATTEMPTS"
    assert login("missing@test.local", "wrong").status_code == 429
    assert login(other, "test1234").status_code == 200
    current += LOGIN_FAIL_WINDOW_SEC
    assert login(email, "test1234").status_code == 200


def test_successful_login_clears_failures_and_password_change_counts(client, monkeypatch):
    monkeypatch.setattr(auth, "login_allowed", lambda ip: True)
    email = signup(client)["email"]

    def change_with_wrong_password():
        return client.post("/api/auth/password", json={"current_password": "wrong", "new_password": "new-test1234"})

    for _ in range(LOGIN_FAIL_PER_EMAIL - 1):
        assert change_with_wrong_password().status_code == 400
    assert client.post("/api/auth/login", json={"email": email, "password": "test1234"}).status_code == 200
    for _ in range(LOGIN_FAIL_PER_EMAIL):
        assert change_with_wrong_password().status_code == 400
    assert client.post("/api/auth/login", json={"email": email, "password": "test1234"}).status_code == 429
