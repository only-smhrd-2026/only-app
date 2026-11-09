"""오늘의 한 장 선정 (FR-ME-004, FR-ME-005, D44).

가족방의 사용 가능한 FAMILY 사진 중 오늘 업로드와 최근 14일 내 대화 완료 사진을 제외하고 무작위 1장.
후보가 0장이면(사진이 적은 방이 14일 안에 다 이야기함) 가장 오래전에 이야기한 사진을 다시 고른다.
INSERT … ON CONFLICT (room_id, pick_date) DO NOTHING 이라 잡과 지연 보정(D9)이 동시에 돌아도 하루 1장.
"""

from __future__ import annotations

import random
from datetime import date, datetime, time, timedelta

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.config import TZ
from app.models import DailyPick, Photo


def today_pick(db: Session, room_id: int, today: date) -> DailyPick | None:
    return db.scalar(select(DailyPick).where(DailyPick.room_id == room_id, DailyPick.pick_date == today))


def select_pick(db: Session, room_id: int, today: date) -> DailyPick | None:
    usable = (
        Photo.room_id == room_id,
        Photo.status == "ACTIVE",
        Photo.source == "FAMILY",
        Photo.usable.is_not(False),
        Photo.uploaded_at < datetime.combine(today, time.min, tzinfo=TZ),
    )
    recent = select(DailyPick.photo_id).where(
        DailyPick.room_id == room_id,
        DailyPick.pick_date >= today - timedelta(days=14),
        DailyPick.status == "COMPLETED",
    )
    candidates = db.scalars(select(Photo.photo_id).where(*usable, Photo.photo_id.not_in(recent))).all()
    if candidates:
        photo_id = random.choice(candidates)
    else:
        # 14일 안에 다 이야기한 방(사진이 적은 방)도 비우지 않는다: 가장 오래전에 이야기한 사진부터 다시 (D44)
        last_done = (
            select(DailyPick.photo_id, func.max(DailyPick.pick_date).label("done"))
            .where(DailyPick.room_id == room_id, DailyPick.status == "COMPLETED")
            .group_by(DailyPick.photo_id)
            .subquery()
        )
        photo_id = db.scalar(
            select(Photo.photo_id)
            .outerjoin(last_done, last_done.c.photo_id == Photo.photo_id)
            .where(*usable)
            .order_by(last_done.c.done.asc().nulls_first(), Photo.photo_id)
            .limit(1)
        )
        if photo_id is None:  # 쓸 수 있는 사진 자체가 없음(오늘 올린 사진뿐이거나 usable=false 뿐)
            return None
    stmt = (
        pg_insert(DailyPick)
        .values(room_id=room_id, pick_date=today, photo_id=photo_id, status="PENDING")
        .on_conflict_do_nothing(constraint="uq_daily_picks_room_id_pick_date")
    )
    db.execute(stmt)
    db.commit()
    return today_pick(db, room_id, today)
