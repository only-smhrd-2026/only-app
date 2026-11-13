"""가족 알림 목록·읽음 처리 (FR-NT-003)."""

from fastapi import APIRouter
from sqlalchemy import func, select, update

from app.config import NOTI_LIST_LIMIT, now_kst
from app.deps import DB, CurrentUser
from app.errors import ApiError
from app.models import Notification, RoomMember
from app.schemas.notifications import NotificationListOut, NotificationOut

router = APIRouter(prefix="/notifications", tags=["notifications"])


def mine(user_id: int):
    """현재 참여 중인 가족방에서 내게 온 가족용 알림만 공개한다."""
    return (
        Notification.target_type == "FAMILY",
        Notification.target_user_id == user_id,
        Notification.room_id.in_(
            select(RoomMember.room_id).where(RoomMember.user_id == user_id, RoomMember.removed_at.is_(None))
        ),
    )


@router.get("", response_model=NotificationListOut)
def list_notifications(user: CurrentUser, db: DB):
    notifications = db.scalars(
        select(Notification)
        .where(*mine(user.user_id))
        .order_by(Notification.sent_at.desc(), Notification.notification_id.desc())
        .limit(NOTI_LIST_LIMIT)
    )
    unread = db.scalar(
        select(func.count()).select_from(Notification).where(*mine(user.user_id), Notification.read_at.is_(None))
    )
    return NotificationListOut(
        notifications=[
            NotificationOut(
                notification_id=n.notification_id,
                room_id=n.room_id,
                kind=n.kind,
                title=n.title,
                body=n.body,
                link_screen=n.link_screen,
                sent_at=n.sent_at,
                read_at=n.read_at,
            )
            for n in notifications
        ],
        unread=unread,
    )


@router.post("/{notification_id}/read", status_code=204)
def read_notification(notification_id: int, user: CurrentUser, db: DB):
    notification = db.scalar(
        select(Notification).where(Notification.notification_id == notification_id, *mine(user.user_id))
    )
    if notification is None:
        raise ApiError(404, "NOTIFICATION_NOT_FOUND", "알림을 찾을 수 없어요")
    db.execute(
        update(Notification)
        .where(Notification.notification_id == notification_id, Notification.read_at.is_(None))
        .values(read_at=now_kst())
    )
    db.commit()
