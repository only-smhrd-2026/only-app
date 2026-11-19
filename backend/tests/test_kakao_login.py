"""카카오 로그인 (routers/kakao.py). 실제 카카오 서버는 부르지 않는다 — httpx.post·get 을 바꿔 끼운다."""

import itertools
import logging
from concurrent.futures import ThreadPoolExecutor
from http.cookies import SimpleCookie
from urllib.parse import parse_qs, urlsplit

import httpx
import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text, update

from app.config import KAKAO_STEP_MIN, KAKAO_TIMEOUT_SEC, LOGIN_RATE_PER_MIN, SESSION_COOKIE_DAYS, now_kst, settings
from app.db import SessionLocal
from app.main import app
from app.models import User
from app.routers import kakao
from app.security import SESSION_COOKIE, create_session_jwt

REST_KEY = "rest-key-123"
REDIRECT = "https://haru.test/api/auth/kakao/callback"
ACCESS_TOKEN = "AT-kakao-access-token-never-stored"
CODE = "code-from-kakao-never-logged"
OUR_ADDRESSES = {"/login", "/login?mode=kakao", "/login?kakao=fail"}  # 화면으로 돌려보내는 고정 주소 전부
SIGNUP = "/api/auth/kakao/signup"
JOIN_BODY = {"name": "김카카오", "terms_agreed": True}

_kakao_ids = itertools.count(9_000_000_001)  # 테스트마다 새 카카오 회원번호 (DB 는 테스트 실행마다 새로 만든다)


@pytest.fixture
def on(monkeypatch):
    monkeypatch.setattr(settings, "KAKAO_REST_KEY", REST_KEY)
    monkeypatch.setattr(settings, "KAKAO_REDIRECT_URI", REDIRECT)


def _fake_kakao(monkeypatch, kakao_id, *, nickname="카카오별명", token_status=200, user_status=200, me=None):
    """카카오 서버 흉내. 서버가 카카오에 보낸 요청을 calls 에 모은다."""
    calls = []

    def fake_post(url, **kw):
        calls.append(("POST", url, kw))
        body = {"token_type": "bearer", "access_token": ACCESS_TOKEN, "refresh_token": "RT-" + ACCESS_TOKEN}
        if token_status != 200:
            body = {"error": "invalid_grant", "error_description": f"code={CODE}", "error_code": "KOE320"}
        return httpx.Response(token_status, json=body, request=httpx.Request("POST", url))

    def fake_get(url, **kw):
        calls.append(("GET", url, kw))
        body = me if me is not None else {"id": kakao_id, "kakao_account": {"profile": {"nickname": nickname}}}
        return httpx.Response(user_status, json=body, request=httpx.Request("GET", url))

    monkeypatch.setattr(kakao.httpx, "post", fake_post)
    monkeypatch.setattr(kakao.httpx, "get", fake_get)
    return calls


def _set_cookies(response) -> SimpleCookie:
    cookies = SimpleCookie()
    for raw in response.headers.get_list("set-cookie"):
        cookies.load(raw)
    return cookies


def _assert_step_cookie(morsel, *, secure=False):
    assert morsel["httponly"] is True
    assert morsel["samesite"].lower() == "lax"
    assert morsel["path"] == "/api/auth/kakao"
    assert int(morsel["max-age"]) == KAKAO_STEP_MIN * 60 == 600
    assert bool(morsel["secure"]) is secure


def _redirect(response) -> str:
    """302 이고, 가는 곳이 우리 고정 주소나 카카오 인가 주소일 때만 통과."""
    assert response.status_code == 302, response.text
    location = response.headers["location"]
    assert location in OUR_ADDRESSES or location.startswith("https://kauth.kakao.com/oauth/authorize?"), location
    return location


def _start(client) -> str:
    location = _redirect(client.get("/api/auth/kakao/start", follow_redirects=False))
    return parse_qs(urlsplit(location).query)["state"][0]


def _callback(client, state, **params):
    return client.get(
        "/api/auth/kakao/callback", params={"code": CODE, "state": state} | params, follow_redirects=False
    )


def _login(client) -> str:
    """시작 → 카카오에서 돌아옴. 돌아간 주소를 준다."""
    return _redirect(_callback(client, _start(client)))


def _jar(client, name) -> str:
    return next(c.value for c in client.cookies.jar if c.name == name)


def _count(kakao_id) -> int:
    with SessionLocal() as db:
        return db.scalar(select(func.count()).select_from(User).where(User.kakao_id == str(kakao_id)))


def _server_log(caplog) -> str:
    """서버가 남긴 로그만 — 테스트 클라이언트(httpx·httpx2)가 남기는 요청 주소 줄은 뺀다."""
    return "\n".join(record.getMessage() for record in caplog.records if not record.name.startswith("httpx"))


def _join(client, kakao_id, monkeypatch) -> dict:
    """처음 온 회원이 카카오에서 돌아와 이름·약관으로 가입까지."""
    _fake_kakao(monkeypatch, kakao_id)
    assert _login(client) == "/login?mode=kakao"
    result = client.post(SIGNUP, json=JOIN_BODY)
    assert result.status_code == 201, result.text
    return result.json()["user"]


@pytest.mark.parametrize(("key", "redirect"), [("", ""), (REST_KEY, ""), ("", REDIRECT)])
def test_off_without_keys(client, monkeypatch, key, redirect):
    monkeypatch.setattr(settings, "KAKAO_REST_KEY", key)
    monkeypatch.setattr(settings, "KAKAO_REDIRECT_URI", redirect)
    assert client.get("/api/auth/providers").json() == {"kakao": False}
    for response in (
        client.get("/api/auth/kakao/start", follow_redirects=False),
        client.get("/api/auth/kakao/callback", params={"code": CODE, "state": "x"}, follow_redirects=False),
        client.get(SIGNUP),
        client.post(SIGNUP, json=JOIN_BODY),
    ):
        assert response.status_code == 404 and response.json()["code"] == "KAKAO_OFF"
        assert "set-cookie" not in response.headers


def test_start_sends_to_kakao_with_state_cookie(client, on, monkeypatch):
    assert client.get("/api/auth/providers").json() == {"kakao": True}
    monkeypatch.setattr(settings, "KAKAO_CLIENT_SECRET", "client-secret")  # 인가 주소에는 싣지 않는다
    response = client.get("/api/auth/kakao/start", follow_redirects=False)
    url = urlsplit(_redirect(response))
    assert (url.scheme, url.netloc, url.path) == ("https", "kauth.kakao.com", "/oauth/authorize")
    query = parse_qs(url.query)
    state = query.pop("state")[0]
    assert query == {"response_type": ["code"], "client_id": [REST_KEY], "redirect_uri": [REDIRECT]}
    assert len(state) >= 43  # 무작위 32바이트 (base64url)
    cookie = _set_cookies(response)[kakao.STATE_COOKIE]
    assert cookie.value == state
    _assert_step_cookie(cookie)
    assert _start(client) != state  # 부를 때마다 새 값

    monkeypatch.setattr(settings, "APP_ENV", "deploy")
    again = client.get("/api/auth/kakao/start", follow_redirects=False)
    _assert_step_cookie(_set_cookies(again)[kakao.STATE_COOKIE], secure=True)


@pytest.mark.parametrize("case", ["no_cookie", "other_state", "no_state", "not_ascii"])
def test_callback_rejects_wrong_state(client, on, monkeypatch, case):
    calls = _fake_kakao(monkeypatch, next(_kakao_ids))
    state = _start(client)
    if case == "no_cookie":
        client.cookies.clear()
    sent = {"no_cookie": state, "other_state": state[::-1], "no_state": "", "not_ascii": "가나다"}[case]
    response = _callback(client, sent)
    assert response.status_code == 400 and response.json()["code"] == "KAKAO_STATE"
    assert calls == []  # 카카오 서버를 부르기 전에 막는다
    assert "set-cookie" not in response.headers
    assert client.get("/api/auth/me").status_code == 401


@pytest.mark.parametrize(
    ("case", "kakao_calls", "logged"),
    [
        ("token_400", 1, "kakao token status=400"),
        ("token_redirect", 1, "kakao token status=302"),  # 다른 주소로 따라가지 않는다
        ("token_timeout", 0, "kakao callback error=ReadTimeout"),
        ("user_401", 2, "kakao user status=401"),
        ("id_not_number", 2, "kakao callback error=ValueError"),
        ("no_id", 2, "kakao callback error=KeyError"),
        ("canceled", 0, ""),  # 카카오 화면에서 동의를 취소 — code 없이 돌아온다
    ],
)
def test_kakao_failure_returns_to_fixed_address(client, on, monkeypatch, caplog, case, kakao_calls, logged):
    caplog.set_level(logging.DEBUG)
    kakao_id = next(_kakao_ids)
    calls = _fake_kakao(
        monkeypatch,
        kakao_id,
        token_status={"token_400": 400, "token_redirect": 302}.get(case, 200),
        user_status=401 if case == "user_401" else 200,
        me={"id_not_number": {"id": str(kakao_id)}, "no_id": {"msg": "no id"}}.get(case),
    )
    if case == "token_timeout":

        def slow(url, **kw):
            raise httpx.ReadTimeout("slow")

        monkeypatch.setattr(kakao.httpx, "post", slow)
    state = _start(client)
    params = {"code": "", "error": "access_denied"} if case == "canceled" else {}
    response = _callback(client, state, **params)
    assert _redirect(response) == "/login?kakao=fail"
    cookies = _set_cookies(response)
    assert set(cookies) == {kakao.STATE_COOKIE} and cookies[kakao.STATE_COOKIE]["max-age"] == "0"  # state 만 지운다
    assert _count(kakao_id) == 0
    assert client.get("/api/auth/me").status_code == 401
    assert client.get(SIGNUP).status_code == 401
    assert len(calls) == kakao_calls
    log = _server_log(caplog)
    assert logged in log and not any(secret in log for secret in (ACCESS_TOKEN, CODE, state))
    assert _callback(client, state).status_code == 400  # state 는 한 번만 쓴다


def test_new_member_waits_for_terms_without_account(client, on, monkeypatch):
    kakao_id = next(_kakao_ids)
    calls = _fake_kakao(monkeypatch, kakao_id)
    response = _callback(client, _start(client))
    assert _redirect(response) == "/login?mode=kakao"
    assert _count(kakao_id) == 0  # 약관 동의 전에는 계정을 만들지 않는다
    cookies = _set_cookies(response)
    assert set(cookies) == {kakao.STATE_COOKIE, kakao.JOIN_COOKIE}  # 로그인 쿠키는 아직 없다
    _assert_step_cookie(cookies[kakao.JOIN_COOKIE])
    assert client.get("/api/auth/me").status_code == 401
    assert client.get(SIGNUP).json() == {"nickname": "카카오별명"}

    (_, token_url, token_kw), (_, user_url, user_kw) = calls
    assert token_url == "https://kauth.kakao.com/oauth/token"
    assert token_kw["data"] == {
        "grant_type": "authorization_code",
        "client_id": REST_KEY,
        "redirect_uri": REDIRECT,
        "code": CODE,
    }
    assert user_url == "https://kapi.kakao.com/v2/user/me"
    assert user_kw["headers"] == {"Authorization": f"Bearer {ACCESS_TOKEN}"}
    for kw in (token_kw, user_kw):
        assert kw["timeout"] == KAKAO_TIMEOUT_SEC == 5.0 and kw["follow_redirects"] is False

    # Client Secret 을 켠 앱이면 토큰 요청 본문에 싣는다
    monkeypatch.setattr(settings, "KAKAO_CLIENT_SECRET", "client-secret")
    calls.clear()
    assert _login(client) == "/login?mode=kakao"
    assert calls[0][2]["data"]["client_secret"] == "client-secret"


def test_signup_needs_join_cookie_and_terms(client, on, monkeypatch):
    kakao_id = next(_kakao_ids)
    _fake_kakao(monkeypatch, kakao_id, nickname="")
    for response in (client.get(SIGNUP), client.post(SIGNUP, json=JOIN_BODY)):  # 카카오를 거치지 않고 바로
        assert response.status_code == 401 and response.json()["code"] == "KAKAO_JOIN_EXPIRED"

    assert _login(client) == "/login?mode=kakao"
    assert client.get(SIGNUP).json() == {"nickname": ""}  # 닉네임 동의를 안 했으면 빈 칸
    for bad in ({"name": "김카카오", "terms_agreed": False}, {"name": "김카카오"}, {"name": "", "terms_agreed": True}):
        assert client.post(SIGNUP, json=bad).status_code == 422
    assert _count(kakao_id) == 0 and client.get("/api/auth/me").status_code == 401

    result = client.post(SIGNUP, json=JOIN_BODY)
    assert result.status_code == 201
    user = result.json()["user"]
    assert user == user | {"login_type": "KAKAO", "email": None, "name": "김카카오"}
    cookies = _set_cookies(result)
    assert cookies[kakao.JOIN_COOKIE]["max-age"] == "0"  # 가입 대기 쿠키는 쓰고 지운다
    session = cookies[SESSION_COOKIE]  # 이메일 로그인과 같은 쿠키
    assert session["path"] == "/" and int(session["max-age"]) == SESSION_COOKIE_DAYS * 86400
    assert session["httponly"] is True and session["samesite"].lower() == "lax"
    assert client.get("/api/auth/me").json()["user_id"] == user["user_id"]
    with SessionLocal() as db:
        row = db.scalar(select(User).where(User.kakao_id == str(kakao_id)))
        assert row.user_id == user["user_id"] and row.status == "ACTIVE"
        assert row.terms_agreed_at is not None and row.password_hash is None
    assert _count(kakao_id) == 1


def test_signup_twice_or_at_once_makes_one_account(client, on, monkeypatch):
    kakao_id = next(_kakao_ids)
    _fake_kakao(monkeypatch, kakao_id)
    assert _login(client) == "/login?mode=kakao"
    cookie = {"Cookie": f"{kakao.JOIN_COOKIE}={_jar(client, kakao.JOIN_COOKIE)}"}

    def press(name):
        return TestClient(app).post(SIGNUP, json={"name": name, "terms_agreed": True}, headers=cookie)

    with ThreadPoolExecutor(max_workers=4) as pool:  # 같은 가입 대기 쿠키로 동시에
        results = list(pool.map(press, ["하나", "둘", "셋", "넷"]))
    results.append(press("다섯"))  # 끝난 뒤 한 번 더
    assert [r.status_code for r in results] == [201] * 5
    assert len({r.json()["user"]["user_id"] for r in results}) == 1
    assert _count(kakao_id) == 1


def test_returning_member_logs_into_same_account(client, on, monkeypatch):
    kakao_id = next(_kakao_ids)
    user = _join(client, kakao_id, monkeypatch)
    assert client.post("/api/auth/logout").status_code == 200
    assert client.get("/api/auth/me").status_code == 401

    response = _callback(client, _start(client))
    assert _redirect(response) == "/login"
    cookies = _set_cookies(response)
    assert set(cookies) == {kakao.STATE_COOKIE, SESSION_COOKIE}  # 가입 대기 쿠키는 주지 않는다
    assert int(cookies[SESSION_COOKIE]["max-age"]) == SESSION_COOKIE_DAYS * 86400
    assert client.get("/api/auth/me").json()["user_id"] == user["user_id"]
    assert _count(kakao_id) == 1
    with SessionLocal() as db:
        assert db.get(User, user["user_id"]).last_login_at is not None


def test_closed_account_is_not_logged_in(client, on, monkeypatch):
    kakao_id = next(_kakao_ids)
    user = _join(client, kakao_id, monkeypatch)
    with SessionLocal() as db:
        db.execute(update(User).where(User.user_id == user["user_id"]).values(status="WITHDRAWN"))
        db.commit()
    client.cookies.clear()

    response = _callback(client, _start(client))
    assert _redirect(response) == "/login?kakao=fail"
    assert set(_set_cookies(response)) == {kakao.STATE_COOKIE}
    assert client.get("/api/auth/me").status_code == 401
    # 가입 대기 쿠키가 남아 있던 브라우저도 그 계정으로 못 들어온다
    cookie = {"Cookie": f"{kakao.JOIN_COOKIE}={kakao._join_token(str(kakao_id), '')}"}
    closed = client.post(SIGNUP, json=JOIN_BODY, headers=cookie)
    assert closed.status_code == 403 and closed.json()["code"] == "KAKAO_ACCOUNT_CLOSED"
    assert SESSION_COOKIE not in _set_cookies(closed) and _count(kakao_id) == 1


def test_join_cookie_and_session_cookie_are_not_interchangeable(client, on, monkeypatch):
    kakao_id = next(_kakao_ids)
    _fake_kakao(monkeypatch, kakao_id)
    assert _login(client) == "/login?mode=kakao"
    join = _jar(client, kakao.JOIN_COOKIE)
    assert jwt.decode(join, options={"verify_signature": False}).keys() == {"aud", "kakao_id", "nickname", "iat", "exp"}
    client.cookies.clear()

    # 가입 대기 쿠키를 로그인 쿠키 자리에 넣어도 로그인되지 않는다
    assert client.get("/api/auth/me", headers={"Cookie": f"{SESSION_COOKIE}={join}"}).status_code == 401
    # 로그인 쿠키·시간이 지난 토큰·다른 키로 서명한 토큰·다른 용도 토큰은 가입 대기 쿠키로 통하지 않는다
    other = _join(client, next(_kakao_ids), monkeypatch)
    client.cookies.clear()
    now = int(now_kst().timestamp())
    claims = {"aud": kakao.JOIN_AUD, "kakao_id": str(kakao_id), "nickname": "", "iat": now, "exp": now + 600}
    forged = [
        create_session_jwt(other["user_id"]),
        jwt.encode(claims | {"iat": now - 700, "exp": now - 100}, settings.JWT_SECRET, algorithm="HS256"),
        jwt.encode(claims, "x" * 48, algorithm="HS256"),
        jwt.encode(claims | {"aud": "other"}, settings.JWT_SECRET, algorithm="HS256"),
        "",
    ]
    for token in forged:
        response = client.post(SIGNUP, json=JOIN_BODY, headers={"Cookie": f"{kakao.JOIN_COOKIE}={token}"})
        assert response.status_code == 401 and response.json()["code"] == "KAKAO_JOIN_EXPIRED"
    assert _count(kakao_id) == 0


def test_access_token_is_never_stored_logged_or_sent_to_browser(client, on, monkeypatch, caplog):
    caplog.set_level(logging.DEBUG)
    kakao_id = next(_kakao_ids)
    _fake_kakao(monkeypatch, kakao_id)
    seen = []  # 브라우저로 나간 것(머리글·본문) + DB 줄 + 서버 로그

    def keep(response):
        seen.append(" ".join(f"{k}: {v}" for k, v in response.headers.multi_items()) + response.text)
        return response

    assert _redirect(keep(_callback(client, _start(client)))) == "/login?mode=kakao"
    assert keep(client.get(SIGNUP)).status_code == 200
    assert keep(client.post(SIGNUP, json=JOIN_BODY)).status_code == 201
    assert keep(client.post("/api/auth/logout")).status_code == 200
    assert _redirect(keep(_callback(client, _start(client)))) == "/login"
    with SessionLocal() as db:
        row = db.execute(text("SELECT row_to_json(u)::text FROM users u WHERE kakao_id = :k"), {"k": str(kakao_id)})
        seen.append(row.scalar_one())
    log = _server_log(caplog)
    assert "카카오별명" not in log and CODE not in log  # 닉네임·인가 코드도 로그에 없다 (D15)
    assert str(kakao_id) in seen[-1]  # DB 줄을 제대로 읽었는지
    assert not any(ACCESS_TOKEN in part for part in [*seen, log])  # refresh token 도 같은 글자를 품고 있다


def test_redirects_ignore_addresses_from_outside(client, on, monkeypatch):
    _fake_kakao(monkeypatch, next(_kakao_ids))
    evil = {
        "next": "https://evil.test/",
        "redirect": "//evil.test",
        "redirect_uri": "https://evil.test/cb",
        "return_to": "https://evil.test/",
    }
    headers = {"host": "evil.test", "x-forwarded-host": "evil.test", "referer": "https://evil.test/"}
    start = client.get("/api/auth/kakao/start", params=evil, headers=headers, follow_redirects=False)
    assert parse_qs(urlsplit(_redirect(start)).query)["redirect_uri"] == [REDIRECT]  # 요청의 Host 가 아니라 설정값
    assert "evil.test" not in start.headers["location"]

    def back():
        state = _start(client)
        return client.get(
            "/api/auth/kakao/callback",
            params={"code": CODE, "state": state} | evil,
            headers=headers | {"Cookie": f"{kakao.STATE_COOKIE}={state}"},
            follow_redirects=False,
        )

    assert _redirect(back()) == "/login?mode=kakao"
    monkeypatch.setattr(kakao.httpx, "post", lambda url, **kw: httpx.Response(500, request=httpx.Request("POST", url)))
    assert _redirect(back()) == "/login?kakao=fail"


def test_callback_stops_calling_kakao_over_ip_limit(client, on, monkeypatch):
    calls = _fake_kakao(monkeypatch, next(_kakao_ids), token_status=400)
    for _ in range(LOGIN_RATE_PER_MIN):
        assert _login(client) == "/login?kakao=fail"
    assert len(calls) == LOGIN_RATE_PER_MIN
    assert _login(client) == "/login?kakao=fail"  # 상한을 넘으면 카카오를 부르지 않고 돌려보낸다
    assert len(calls) == LOGIN_RATE_PER_MIN


def test_password_api_does_not_crash_for_kakao_member(client, on, monkeypatch):
    """카카오 회원은 비밀번호가 없다 — 비밀번호 바꾸기가 500 을 내거나 성공하지 않는다."""
    kakao_id = next(_kakao_ids)
    _join(client, kakao_id, monkeypatch)
    result = client.post("/api/auth/password", json={"current_password": "anything-1", "new_password": "new-test1234"})
    assert 400 <= result.status_code < 500
    with SessionLocal() as db:
        assert db.scalar(select(User.password_hash).where(User.kakao_id == str(kakao_id))) is None
