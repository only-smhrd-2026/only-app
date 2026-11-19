"""위급 알림 (D55 마음 위급 + 11/19 몸 위급) — 가족 홈 긴급 카드와 '아직 연락한 가족이 없어요' 다시 알림.

- raise_alert: 대화에서 위급이 감지되면 urgent_alerts 한 줄 + 가족 모두에게 알림. 대화 내용은 넣지 않는다 (D15).
- ack: 가족이 [제가 연락했어요]를 누르면 처음 누른 사람만 남는다 — 다른 가족에게 '○○님이 연락했어요'로 보인다.
- remind: URGENT_REMIND_MIN 분 동안 아무도 누르지 않으면 한 번만 다시 알린다 (예약 작업).
알림 종류는 둘 다 MOOD_URGENT(notifications.kind 는 D55 때 이름 그대로) — 마음·몸 구분은 urgent_alerts.kind 가 한다.
"""

from __future__ import annotations

import uuid
from datetime import timedelta

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.config import URGENT_REMIND_MIN, URGENT_SHOW_HOURS, now_kst
from app.models import FamilyRoom, UrgentAlert
from app.routers.devices import notify_family

# (알림 제목, 본문) — {who} = '이름 호칭'
TEXTS = {
    "MOOD": ("지금 전화 한 통 드려 보세요", "{who}께서 많이 힘드신 것 같아요. 무슨 말씀을 하셨는지는 전하지 않아요."),
    "BODY": (
        "지금 바로 전화해 보세요",
        "{who}께서 몸이 많이 불편하다고 하셨어요. 전화를 안 받으시면 가까운 분께 부탁하거나 119 에 알려 주세요.",
    ),
}
REMIND = (
    "아직 연락한 가족이 없어요",
    "{who}께 급한 알림이 있었어요. 전화해 보시고 가족 홈에서 [제가 연락했어요]를 눌러 주세요.",
)


def _who(room: FamilyRoom) -> str:
    return f"{room.elder_name} {room.elder_honorific}"


def raise_alert(db: Session, room: FamilyRoom, session_id: uuid.UUID | None, kind: str) -> None:
    """위급 1건: 긴급 카드용 줄 + 가족 모두에게 알림. 커밋은 호출자가 한다.

    같은 방에 아직 아무도 확인하지 않은 같은 종류 알림이 URGENT_REMIND_MIN 분 안에 있으면 새로 만들지 않는다 —
    어르신 기기에서 위급한 말을 되풀이해(대화를 새로 열어 가며) 가족 폰을 알림으로 뒤덮지 못하게 (11/19 보안 점검).
    대화를 위급으로 마무리하는 것은 그대로이고, 그 알림이 계속 확인 안 되면 remind 가 한 번 더 알린다.
    """
    open_recent = db.scalar(
        select(UrgentAlert.alert_id)
        .where(
            UrgentAlert.room_id == room.room_id,
            UrgentAlert.kind == kind,
            UrgentAlert.acked_at.is_(None),
            UrgentAlert.created_at >= now_kst() - timedelta(minutes=URGENT_REMIND_MIN),
        )
        .limit(1)
    )
    if open_recent is not None:
        return
    title, body = TEXTS[kind]
    db.add(UrgentAlert(room_id=room.room_id, session_id=session_id, kind=kind))
    notify_family(db, room.room_id, "MOOD_URGENT", title, body.format(who=_who(room)), "HOME_001")


def latest(db: Session, room_id: int) -> UrgentAlert | None:
    """가족 홈에 보일 위급 알림 — 최근 URGENT_SHOW_HOURS 시간 안의 가장 새 것. 확인된 것도 그동안은 보인다."""
    since = now_kst() - timedelta(hours=URGENT_SHOW_HOURS)
    return db.scalar(
        select(UrgentAlert)
        .where(UrgentAlert.room_id == room_id, UrgentAlert.created_at >= since)
        .order_by(UrgentAlert.alert_id.desc())
        .limit(1)
    )


def ack(db: Session, room_id: int, alert_id: int, user_id: int) -> UrgentAlert | None:
    """[제가 연락했어요] — 그 방의 아직 열린 알림을 그 알림까지 한꺼번에 닫는다(처음 누른 사람만 남는다)."""
    db.execute(
        update(UrgentAlert)
        .where(UrgentAlert.room_id == room_id, UrgentAlert.alert_id <= alert_id, UrgentAlert.acked_at.is_(None))
        .values(acked_by=user_id, acked_at=now_kst())
    )
    db.commit()
    alert = db.get(UrgentAlert, alert_id)
    return alert if alert is not None and alert.room_id == room_id else None


def remind(db: Session) -> int:
    """아무도 확인하지 않은 위급 알림을 가족에게 한 번 더 — 알림마다 한 번만. → 다시 알린 방 수."""
    now = now_kst()
    rows = db.scalars(
        select(UrgentAlert)
        .where(
            UrgentAlert.acked_at.is_(None),
            UrgentAlert.reminded_at.is_(None),
            UrgentAlert.created_at <= now - timedelta(minutes=URGENT_REMIND_MIN),
            UrgentAlert.created_at >= now - timedelta(hours=URGENT_SHOW_HOURS),
        )
        .with_for_update(skip_locked=True)
    ).all()
    told: set[int] = set()
    for alert in rows:
        alert.reminded_at = now
        if alert.room_id in told:  # 한 방에 열린 알림이 여럿이어도 다시 알림은 한 번
            continue
        told.add(alert.room_id)
        title, body = REMIND
        who = _who(db.get(FamilyRoom, alert.room_id))
        notify_family(db, alert.room_id, "MOOD_URGENT", title, body.format(who=who), "HOME_001")
    db.commit()
    return len(told)
