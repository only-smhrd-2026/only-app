import threading
import time
from concurrent.futures import ThreadPoolExecutor

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


def test_concurrent_wrong_passwords_stop_at_the_limit(client, monkeypatch):
    """같은 이메일로 틀린 비밀번호가 한꺼번에 와도 상한까지만 비밀번호 비교에 들어간다 (11/19 다듬기).

    '막혔는지 확인'과 '실패 기록' 사이에 느린 bcrypt 비교가 있어, 둘을 따로 하면 동시에 온 요청이 전부 확인을 통과한다.
    """
    current = 1000
    monkeypatch.setattr(security, "monotonic", lambda: current)
    monkeypatch.setattr(auth, "login_allowed", lambda ip: True)
    email = signup(client)["email"]
    total = LOGIN_FAIL_PER_EMAIL * 2
    compared = []  # 비밀번호 비교까지 들어간 요청
    release = threading.Event()
    real_verify = auth.verify_password

    def held_verify(password, password_hash):
        compared.append(password)
        release.wait(10)  # 느린 bcrypt 자리 — 나머지 요청이 모두 도착할 때까지 비교를 끝내지 않는다
        return real_verify(password, password_hash)

    monkeypatch.setattr(auth, "verify_password", held_verify)

    def login(password):
        return client.post("/api/auth/login", json={"email": email, "password": password})

    with ThreadPoolExecutor(total) as pool:
        futures = [pool.submit(login, "wrong") for _ in range(total)]
        deadline = time.monotonic() + 5
        # 요청이 전부 '비교 중'이거나 '거절됨'이 될 때까지 기다린다. 상한을 넘겨 비교에 들어갔으면 바로 실패
        while (
            len(compared) + sum(f.done() for f in futures) < total
            and len(compared) <= LOGIN_FAIL_PER_EMAIL
            and time.monotonic() < deadline
        ):
            time.sleep(0.01)
        release.set()
        codes = sorted(f.result().status_code for f in futures)

    assert len(compared) == LOGIN_FAIL_PER_EMAIL
    assert codes == [401] * LOGIN_FAIL_PER_EMAIL + [429] * (total - LOGIN_FAIL_PER_EMAIL)
    blocked = login("test1234")  # 맞는 비밀번호도 막힌 동안은 비교하지 않는다
    assert blocked.status_code == 429 and blocked.json()["code"] == "TOO_MANY_ATTEMPTS"
    assert len(compared) == LOGIN_FAIL_PER_EMAIL
    current += LOGIN_FAIL_WINDOW_SEC
    assert login("test1234").status_code == 200


def test_correct_password_leaves_no_count(client, monkeypatch):
    """평소 흐름은 그대로: 맞는 비밀번호는 비교 전에 잡아 둔 칸까지 지워져 셈에 남지 않는다."""
    monkeypatch.setattr(auth, "login_allowed", lambda ip: True)
    email = signup(client)["email"]

    def login(password):
        return client.post("/api/auth/login", json={"email": email, "password": password}).status_code

    # 비밀번호 바꾸기: 지금 비밀번호가 맞으면 새 비밀번호가 같아 거절돼도 실패로 세지 않는다
    same = {"current_password": "test1234", "new_password": "test1234"}
    assert client.post("/api/auth/password", json=same).json()["code"] == "SAME_PASSWORD"
    assert [login("wrong") for _ in range(LOGIN_FAIL_PER_EMAIL - 1)] == [401] * (LOGIN_FAIL_PER_EMAIL - 1)
    assert login("test1234") == 200  # 위에서 맞은 비교가 셈에 남았다면 여기서 429
    # 성공한 로그인이 셈에 남았다면 아래 열 번째가 429 가 된다
    assert [login("wrong") for _ in range(LOGIN_FAIL_PER_EMAIL)] == [401] * LOGIN_FAIL_PER_EMAIL
    assert login("test1234") == 429
