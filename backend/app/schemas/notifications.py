"""가족 앱 안 알림 목록의 응답 모양."""

from datetime import datetime

from pydantic import BaseModel


class NotificationOut(BaseModel):
    notification_id: int
    room_id: int
    kind: str
    title: str
    body: str | None
    link_screen: str | None
    link_id: int | None = None  # 11/23 일기 알림(DIARY_POSTED·ELDER_REPLY) = diary_id → HOME_002
    sent_at: datetime
    read_at: datetime | None


class NotificationListOut(BaseModel):
    notifications: list[NotificationOut]
    unread: int
