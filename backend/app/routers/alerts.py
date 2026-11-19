"""가족 홈 긴급 카드 (D55 마음 위급 + 11/19 몸 위급).

1. GET  /rooms/{room_id}/alert — 최근 24시간 안의 가장 새 위급 알림. 없으면 null
2. POST /rooms/{room_id}/alerts/{alert_id}/ack — [제가 연락했어요]. 처음 누른 사람만 남고, 다시 눌러도 그대로
"""

from fastapi import APIRouter

from app.deps import DB, CurrentUser, require_member
from app.errors import ApiError
from app.models import UrgentAlert
from app.routers.diaries import _member_names
from app.schemas.alerts import AlertOut
from app.services import alerts

router = APIRouter(prefix="/rooms/{room_id}", tags=["alerts"])


def _out(db, alert: UrgentAlert, user_id: int) -> AlertOut:
    names = _member_names(db, alert.room_id) if alert.acked_by else {}
    return AlertOut(
        alert_id=alert.alert_id,
        kind=alert.kind,
        created_at=alert.created_at,
        acked_at=alert.acked_at,
        acked_by_name=names.get(alert.acked_by),
        acked_by_me=alert.acked_by == user_id,
    )


@router.get("/alert", response_model=AlertOut | None)
def get_alert(room_id: int, user: CurrentUser, db: DB):
    require_member(room_id, user, db)
    alert = alerts.latest(db, room_id)
    return _out(db, alert, user.user_id) if alert else None


@router.post("/alerts/{alert_id}/ack", response_model=AlertOut)
def ack_alert(room_id: int, alert_id: int, user: CurrentUser, db: DB):
    require_member(room_id, user, db)
    alert = alerts.ack(db, room_id, alert_id, user.user_id)
    if alert is None:
        raise ApiError(404, "ALERT_NOT_FOUND", "알림을 찾을 수 없어요")
    return _out(db, alert, user.user_id)
