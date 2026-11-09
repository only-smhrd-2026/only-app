"""오늘의 한 장 선정 (FR-ME-004, FR-ME-005).

가족방의 사용 가능한 FAMILY 사진 중 오늘 업로드와 최근 14일 내 대화 완료 사진을 제외하고 무작위 1장.
INSERT … ON CONFLICT (room_id, pick_date) DO NOTHING 이라 잡과 지연 보정(D9)이 동시에 돌아도 하루 1장.
"""

from __future__ import annotations

import random
from datetime import date, datetime, time, timedelta

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.config import TZ
from app.models import DailyPick, Photo


def today_pick(db: Session, room_id: int, today: date) -> DailyPick | None:
    return db.scalar(select(DailyPick).where(DailyPick.room_id == room_id, DailyPick.pick_date == today))


def select_pick(db: Session, room_id: int, today: date) -> DailyPick | None:
    recent = select(DailyPick.photo_id).where(
        DailyPick.room_id == room_id,
        DailyPick.pick_date >= today - timedelta(days=14),
        DailyPick.status == "COMPLETED",
    )
    candidates = db.scalars(
        select(Photo.photo_id).where(
            Photo.room_id == room_id,
            Photo.status == "ACTIVE",
            Photo.source == "FAMILY",
            Photo.usable.is_not(False),
            Photo.uploaded_at < datetime.combine(today, time.min, tzinfo=TZ),
            Photo.photo_id.not_in(recent),
        )
    ).all()
    if not candidates:
        return None
    stmt = (
        pg_insert(DailyPick)
        .values(room_id=room_id, pick_date=today, photo_id=random.choice(candidates), status="PENDING")
        .on_conflict_do_nothing(constraint="uq_daily_picks_room_id_pick_date")
    )
    db.execute(stmt)
    db.commit()
    return today_pick(db, room_id, today)
