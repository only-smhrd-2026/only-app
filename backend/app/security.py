"""비밀번호 해시(bcrypt), 가족 세션 JWT, 토큰 해시, 쿠키, 로그인 속도 제한 (D2, D20)."""

from __future__ import annotations

import hashlib
import secrets
import time
from collections import defaultdict, deque

import bcrypt
import jwt
from fastapi import Response

from app.config import (
    DEVICE_COOKIE_DAYS,
    LOGIN_RATE_PER_MIN,
    SESSION_COOKIE_DAYS,
    now_kst,
    settings,
)

SESSION_COOKIE = "session"  # 가족 (JWT)
DEVICE_COOKIE = "device"  # 어르신 기기 (토큰 원문; 서버는 SHA-256 해시만 저장)


def hash_password(password: str) -> str:
    # rounds 10: 동기 엔드포인트 CPU 점유 완화 (D3)
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt(rounds=10)).decode()


def verify_password(password: str, password_hash: str | None) -> bool:
    if not password_hash:
        return False
    return bcrypt.checkpw(password.encode(), password_hash.encode())


def create_session_jwt(user_id: int) -> str:
    now = int(now_kst().timestamp())
    payload = {"sub": str(user_id), "iat": now, "exp": now + SESSION_COOKIE_DAYS * 86400}
    return jwt.encode(payload, settings.JWT_SECRET, algorithm="HS256")


def decode_session_jwt(token: str) -> int | None:
    try:
        payload = jwt.decode(token, settings.JWT_SECRET, algorithms=["HS256"])  # alg 고정
        return int(payload["sub"])
    except (jwt.PyJWTError, KeyError, ValueError):
        return None


def new_token() -> str:
    return secrets.token_urlsafe(32)


def sha256_hex(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def set_cookie(response: Response, name: str, value: str, days: int) -> None:
    # Secure 는 dev 에서만 끔 (Safari 가 localhost 의 Secure 쿠키를 거부). 배포는 항상 켬.
    response.set_cookie(
        name,
        value,
        max_age=days * 86400,
        httponly=True,
        secure=not settings.is_dev,
        samesite="lax",
        path="/",
    )


def set_session_cookie(response: Response, user_id: int) -> None:
    set_cookie(response, SESSION_COOKIE, create_session_jwt(user_id), SESSION_COOKIE_DAYS)


def set_device_cookie(response: Response, raw_token: str) -> None:
    set_cookie(response, DEVICE_COOKIE, raw_token, DEVICE_COOKIE_DAYS)


def clear_cookie(response: Response, name: str) -> None:
    response.delete_cookie(name, path="/", httponly=True, secure=not settings.is_dev, samesite="lax")


# ponytail: 프로세스 메모리 카운터 (uvicorn --workers 1 전제, D9). 재시작하면 초기화되지만 무방 (D20).
_login_hits: dict[str, deque[float]] = defaultdict(deque)


def login_allowed(ip: str) -> bool:
    now = time.monotonic()
    hits = _login_hits[ip]
    while hits and now - hits[0] > 60:
        hits.popleft()
    if len(hits) >= LOGIN_RATE_PER_MIN:
        return False
    hits.append(now)
    return True
