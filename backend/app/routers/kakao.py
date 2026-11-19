"""카카오 로그인 (FR-AD-001 2순위). 인가 코드 방식 — 토큰은 서버가 바꾸고, 화면에는 카카오 SDK·키를 넣지 않는다.

/kakao/start(state 쿠키) → 카카오 화면 → /kakao/callback(state 확인 → 토큰 → 회원번호)
  · 이미 가입한 회원: 이메일 로그인과 같은 session 쿠키 → 로그인 화면(LOGIN_001 이 홈·초대 화면으로 보낸다)
  · 처음 온 회원: 계정을 만들지 않고 가입 대기 쿠키(10분)만 → 화면이 이름·약관을 받아 POST /kakao/signup
카카오 access token 은 _kakao_user 안에서만 쓰고 버린다(로그·DB·쿠키에 없음). 카카오에서 믿는 값은 회원번호(id)뿐.
화면으로 돌려보내는 주소는 아래 고정 글자 셋뿐이다 — 바깥에서 받은 주소로 보내지 않는다.
"""

import hmac
import logging
from urllib.parse import urlencode

import httpx
import jwt
from fastapi import APIRouter, Request, Response
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.config import KAKAO_STEP_MIN, KAKAO_TIMEOUT_SEC, now_kst, settings
from app.deps import DB
from app.errors import ApiError
from app.models import User
from app.schemas.auth import AuthOut, UserOut
from app.schemas.kakao import KakaoPendingOut, KakaoSignupIn, ProvidersOut
from app.security import login_allowed, new_token, set_session_cookie

log = logging.getLogger("app.kakao")
router = APIRouter(prefix="/auth", tags=["auth"])

AUTHORIZE_URL = "https://kauth.kakao.com/oauth/authorize"
TOKEN_URL = "https://kauth.kakao.com/oauth/token"
USER_URL = "https://kapi.kakao.com/v2/user/me"

AFTER_LOGIN = "/login"  # LOGIN_001 이 로그인된 것을 보고 홈(초대받았으면 초대 화면)으로 보낸다
AFTER_NEW = "/login?mode=kakao"  # 처음 온 회원 — 이름·약관만 받는 가입 화면
AFTER_FAIL = "/login?kakao=fail"  # 안내 문장을 띄운다

STATE_COOKIE = "kakao_state"  # 내 브라우저가 시작한 로그인인지 확인하는 무작위 값
JOIN_COOKIE = "kakao_join"  # 가입 대기: 서명한 {카카오 회원번호, 닉네임}
JOIN_AUD = "kakao-join"  # 세션 JWT 에는 aud 가 없고 이 토큰에는 sub 가 없다 → 서로 자리를 바꿔 쓸 수 없다
COOKIE_PATH = "/api/auth/kakao"  # 중간 쿠키 둘은 이 주소들에만 실린다


def _enabled() -> bool:
    return bool(settings.KAKAO_REST_KEY and settings.KAKAO_REDIRECT_URI)


def _require_enabled() -> None:
    if not _enabled():
        raise ApiError(404, "KAKAO_OFF", "카카오 로그인은 준비 중이에요")


def _set_step_cookie(response: Response, name: str, value: str) -> None:
    response.set_cookie(
        name,
        value,
        max_age=KAKAO_STEP_MIN * 60,
        httponly=True,
        secure=not settings.is_dev,
        samesite="lax",  # 카카오에서 돌아오는 이동(맨 위 GET)에는 실려야 해서 strict 가 아니다
        path=COOKIE_PATH,
    )


def _clear_step_cookie(response: Response, name: str) -> None:
    response.delete_cookie(name, path=COOKIE_PATH, httponly=True, secure=not settings.is_dev, samesite="lax")


def _go(url: str) -> RedirectResponse:
    """화면으로 돌려보낸다(url 은 위 AFTER_ 셋 중 하나). state 는 한 번 쓰고 지운다."""
    response = RedirectResponse(url, status_code=302)
    _clear_step_cookie(response, STATE_COOKIE)
    return response


def _join_token(kakao_id: str, nickname: str) -> str:
    now = int(now_kst().timestamp())
    payload = {
        "aud": JOIN_AUD,
        "kakao_id": kakao_id,
        "nickname": nickname,
        "iat": now,
        "exp": now + KAKAO_STEP_MIN * 60,
    }
    return jwt.encode(payload, settings.JWT_SECRET, algorithm="HS256")


def _read_join(request: Request) -> tuple[str, str]:
    """가입 대기 쿠키 → (카카오 회원번호, 닉네임). 없거나 10분이 지났거나 다른 용도의 토큰이면 401."""
    try:
        payload = jwt.decode(
            request.cookies.get(JOIN_COOKIE, ""), settings.JWT_SECRET, algorithms=["HS256"], audience=JOIN_AUD
        )
        return payload["kakao_id"], payload["nickname"]
    except (jwt.PyJWTError, KeyError):
        raise ApiError(401, "KAKAO_JOIN_EXPIRED", "카카오 확인 시간이 지났어요. 카카오로 다시 시작해 주세요") from None


def _json(r: httpx.Response, step: str) -> dict:
    if not r.is_success:  # 3xx 도 실패로 본다 (다른 주소로 따라가지 않는다)
        log.warning("kakao %s status=%d", step, r.status_code)  # 본문은 남기지 않는다 — 인가 코드가 들어 있다
        r.raise_for_status()
    return r.json()


def _kakao_user(code: str) -> tuple[str, str]:
    """인가 코드 → (카카오 회원번호, 닉네임). access token 은 이 함수 안에서만 쓰고 버린다."""
    form = {
        "grant_type": "authorization_code",
        "client_id": settings.KAKAO_REST_KEY,
        "redirect_uri": settings.KAKAO_REDIRECT_URI,
        "code": code,
    }
    if settings.KAKAO_CLIENT_SECRET:
        form["client_secret"] = settings.KAKAO_CLIENT_SECRET
    token = _json(httpx.post(TOKEN_URL, data=form, timeout=KAKAO_TIMEOUT_SEC, follow_redirects=False), "token")
    me = _json(
        httpx.get(
            USER_URL,
            headers={"Authorization": f"Bearer {token['access_token']}"},
            timeout=KAKAO_TIMEOUT_SEC,
            follow_redirects=False,
        ),
        "user",
    )
    kakao_id = me["id"]
    if isinstance(kakao_id, bool) or not isinstance(kakao_id, int):
        raise ValueError("kakao id")
    # 닉네임은 이름 칸을 미리 채우는 데만 쓴다 (사용자가 고칠 수 있고, 동의하지 않았으면 없다)
    profile = (me.get("kakao_account") or {}).get("profile") or {}
    return str(kakao_id), str(profile.get("nickname") or "")[:30]


@router.get("/providers", response_model=ProvidersOut)
def providers():
    """로그인 화면이 카카오 버튼을 켤지 정한다. 서버에 키가 없으면 false → 화면은 '준비 중'."""
    return ProvidersOut(kakao=_enabled())


@router.get("/kakao/start", response_class=RedirectResponse, status_code=302)
def kakao_start():
    _require_enabled()
    state = new_token()
    query = urlencode(
        {
            "response_type": "code",
            "client_id": settings.KAKAO_REST_KEY,
            "redirect_uri": settings.KAKAO_REDIRECT_URI,  # 요청의 Host 가 아니라 설정값
            "state": state,
        }
    )
    response = RedirectResponse(f"{AUTHORIZE_URL}?{query}", status_code=302)
    _set_step_cookie(response, STATE_COOKIE, state)
    return response


@router.get("/kakao/callback", response_class=RedirectResponse, status_code=302)
def kakao_callback(request: Request, db: DB, code: str = "", state: str = ""):
    _require_enabled()
    # 내 브라우저가 시작한 로그인인지 본다 (CSRF — 남이 자기 카카오 계정으로 내 브라우저를 로그인시키지 못하게)
    saved = request.cookies.get(STATE_COOKIE, "")
    if not saved or not hmac.compare_digest(saved.encode(), state.encode()):
        raise ApiError(400, "KAKAO_STATE", "카카오 로그인을 처음부터 다시 해 주세요")
    ip = request.client.host if request.client else "unknown"
    # code 가 없는 것은 카카오 화면에서 동의를 취소한 경우. 카카오 서버를 부르는 횟수는 로그인과 같은 IP 상한으로 (D20)
    if not code or not login_allowed(ip):
        return _go(AFTER_FAIL)
    try:
        kakao_id, nickname = _kakao_user(code)
    except Exception as e:  # 카카오 쪽 실패는 어떤 모양이든(시간 초과·4xx·이상한 응답) 로그인 화면으로
        log.warning("kakao callback error=%s", type(e).__name__)  # 예외 종류만 (D15)
        return _go(AFTER_FAIL)
    user = db.scalar(select(User).where(User.kakao_id == kakao_id))
    if user is None:  # 처음 온 회원 — 약관 동의 전이라 계정을 만들지 않는다
        response = _go(AFTER_NEW)
        _set_step_cookie(response, JOIN_COOKIE, _join_token(kakao_id, nickname))
        return response
    if user.status != "ACTIVE":  # 탈퇴 등 — 그 계정으로 로그인시키지 않는다
        return _go(AFTER_FAIL)
    user.last_login_at = now_kst()
    db.commit()
    response = _go(AFTER_LOGIN)
    set_session_cookie(response, user.user_id)
    return response


@router.get("/kakao/signup", response_model=KakaoPendingOut)
def kakao_pending(request: Request):
    """처음 온 카카오 회원의 가입 화면이 이름 칸에 미리 넣을 닉네임. 가입 대기 쿠키가 없으면 401."""
    _require_enabled()
    return KakaoPendingOut(nickname=_read_join(request)[1])


@router.post("/kakao/signup", response_model=AuthOut, status_code=201)
def kakao_signup(body: KakaoSignupIn, request: Request, response: Response, db: DB):
    _require_enabled()
    kakao_id, _ = _read_join(request)
    # 두 번 누르기·동시 요청에도 계정은 하나 (kakao_id UNIQUE) — 이미 있으면 그 계정으로 로그인
    db.execute(
        pg_insert(User)
        .values(login_type="KAKAO", kakao_id=kakao_id, name=body.name, terms_agreed_at=now_kst())
        .on_conflict_do_nothing(index_elements=["kakao_id"])
    )
    db.commit()
    user = db.scalar(select(User).where(User.kakao_id == kakao_id, User.status == "ACTIVE"))
    if not user:
        raise ApiError(403, "KAKAO_ACCOUNT_CLOSED", "이 카카오 계정으로는 들어올 수 없어요")
    _clear_step_cookie(response, JOIN_COOKIE)
    set_session_cookie(response, user.user_id)
    return AuthOut(user=UserOut.model_validate(user))
