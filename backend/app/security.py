"""비밀번호 해시(bcrypt), 가족 세션 JWT, 토큰 해시, 쿠키, 로그인·음성 인식 속도 제한, 하루 상한 (D2, D20, D46)."""

from __future__ import annotations

import hashlib
import secrets
import time
from collections import Counter, defaultdict, deque
from datetime import date

import bcrypt
import jwt
from fastapi import Response

from app.config import (
    DEVICE_COOKIE_DAYS,
    LOGIN_RATE_PER_MIN,
    SESSION_COOKIE_DAYS,
    STT_RATE_PER_MIN,
    now_kst,
    settings,
    today_kst,
)

SESSION_COOKIE = "session"  # 가족 (JWT)
DEVICE_COOKIE = "device"  # 어르신 기기 (토큰 원문; 서버는 SHA-256 해시만 저장)


def hash_password(password: str) -> str:
    # rounds 10: 동기 엔드포인트 CPU 점유 완화 (D3)
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt(rounds=10)).decode()


def verify_password(password: str, password_hash: str | None) -> bool:
    # bcrypt 5 는 72바이트 초과 입력에 ValueError → 500 대신 로그인 실패로
    if not password_hash or len(password.encode()) > 72:
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
_stt_hits: dict[str, deque[float]] = defaultdict(deque)


def _allowed(hits: deque[float], per_min: int) -> bool:
    now = time.monotonic()
    while hits and now - hits[0] > 60:
        hits.popleft()
    if len(hits) >= per_min:
        return False
    hits.append(now)
    return True


def login_allowed(ip: str) -> bool:
    return _allowed(_login_hits[ip], LOGIN_RATE_PER_MIN)


def stt_allowed(ip: str) -> bool:
    """음성 인식은 부를 때마다 돈이 든다(리턴제로는 연결마다 최소 10초 과금). 같은 IP 에서 분당 상한까지만 (D46)."""
    return _allowed(_stt_hits[ip], STT_RATE_PER_MIN)


# ponytail: 서버 전체 하루 횟수도 프로세스 메모리 (워커 1개 D9). 날짜가 키라 한국 자정에 저절로 0.
# 재시작하면 0 부터(그날 재시작 수만큼 더 샐 수 있음), 지난 날 키가 하루 3개씩 남는다. 넘치면 DB 로.
_daily_hits: Counter[tuple[str, date]] = Counter()


def daily_allowed(kind: str, cap: int) -> bool:
    """유료 외부 호출(stt·tts·llm) 서버 전체 하루 상한 (D46). 같은 IP 분당 상한과 별개. 허용하면 1 센다."""
    key = (kind, today_kst())
    if _daily_hits[key] >= cap:
        return False
    _daily_hits[key] += 1
    return True
