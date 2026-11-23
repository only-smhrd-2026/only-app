"""웹 푸시 구독 등록·해제 — 가족은 로그인 쿠키, 어르신 기기는 기기 쿠키. 보내는 쪽은 services/push.py."""

from fastapi import APIRouter
from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.config import PUSH_SUBS_PER_USER, settings
from app.deps import DB, CurrentDevice, CurrentUser
from app.errors import ApiError
from app.models import PushSubscription
from app.schemas.common import OkOut
from app.schemas.push import PushKeyOut, PushPrefs, PushSubscribeIn, PushUnsubscribeIn
from app.services import push

router = APIRouter(tags=["push"])


def _save(db: Session, body: PushSubscribeIn, **owner: int) -> None:
    """endpoint 로 upsert — 같은 브라우저가 다시 오면 그 줄의 주인(user_id 또는 room_id)·키를 지금 것으로 바꾼다."""
    if not push.endpoint_allowed(body.endpoint):
        # 서버가 이 주소로 요청을 보내게 되므로 알려진 푸시 서비스의 https 주소만 받는다 (SSRF)
        raise ApiError(400, "PUSH_ENDPOINT_INVALID", "이 브라우저에서는 알림을 켤 수 없어요")
    values = {
        "user_id": None,
        "room_id": None,
        **owner,
        "p256dh": body.keys.p256dh.rstrip("="),
        "auth": body.keys.auth.rstrip("="),
        "created_at": func.now(),
    }
    db.execute(
        pg_insert(PushSubscription)
        .values(endpoint=body.endpoint, **values)
        .on_conflict_do_update(index_elements=[PushSubscription.endpoint], set_=values)
    )


@router.get("/push/key", response_model=PushKeyOut)
def key():
    """화면이 구독할 때 쓰는 서버 공개 키. 키가 없는 서버(내 PC)는 null — 화면이 알림 카드를 숨긴다."""
    return PushKeyOut(public_key=settings.VAPID_PUBLIC_KEY.rstrip("=") if push.enabled() else None)


@router.post("/push/subscribe", response_model=OkOut)
def subscribe(body: PushSubscribeIn, user: CurrentUser, db: DB):
    """이 브라우저를 내 알림 받는 곳으로 (가족 [알림 켜기]). 다른 사람이 쓰던 브라우저면 그 줄이 내 것으로 바뀐다."""
    _save(db, body, user_id=user.user_id)
    # 한 사람이 주소를 끝없이 넣어 발송 줄을 막지 못하게 최근에 등록한 것만 남긴다 (D8)
    s = PushSubscription
    keep = (
        select(s.subscription_id)
        .where(s.user_id == user.user_id)
        .order_by(s.created_at.desc(), s.subscription_id.desc())
        .limit(PUSH_SUBS_PER_USER)
    )
    db.execute(delete(s).where(s.user_id == user.user_id, s.subscription_id.not_in(keep)))
    db.commit()
    return OkOut()


@router.post("/push/unsubscribe", response_model=OkOut)
def unsubscribe(body: PushUnsubscribeIn, user: CurrentUser, db: DB):
    """이 브라우저로는 그만 받기 (가족 [끄기]·로그아웃). 내 줄만 지운다 — 없거나 남의 것이어도 같은 답."""
    s = PushSubscription
    db.execute(delete(s).where(s.endpoint == body.endpoint, s.user_id == user.user_id))
    db.commit()
    return OkOut()


@router.get("/push/prefs", response_model=PushPrefs)
def get_prefs(user: CurrentUser):
    """내가 끈 폰 알림 묶음 (11/23). 급한 알림은 목록에 없다 — 끌 수 없다."""
    return PushPrefs(muted=user.push_muted)


@router.put("/push/prefs", response_model=PushPrefs)
def put_prefs(body: PushPrefs, user: CurrentUser, db: DB):
    """끈 묶음을 통째로 바꾼다 — 같은 요청이 두 번 와도 같다. 앱 안 알림 목록은 그대로 쌓인다."""
    user.push_muted = sorted(set(body.muted))
    db.commit()
    return PushPrefs(muted=user.push_muted)


@router.post("/elder/push/subscribe", response_model=OkOut)
def elder_subscribe(body: PushSubscribeIn, device: CurrentDevice, db: DB):
    """어르신 기기를 그 가족방의 시간 알림 받는 곳으로. 가족방당 1줄 — 브라우저가 구독을 새로 만들면 옛 줄은 지운다."""
    _save(db, body, room_id=device.room_id)
    s = PushSubscription
    db.execute(delete(s).where(s.room_id == device.room_id, s.endpoint != body.endpoint))
    db.commit()
    return OkOut()
