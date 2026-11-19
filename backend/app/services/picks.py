"""오늘의 한 장 선정 (FR-ME-004, FR-ME-005, D44).

가족방의 사용 가능한 FAMILY 사진 중 오늘 업로드와 최근 14일 내 대화 완료 사진을 제외하고 1장.
무작위지만 어르신 반응으로 무게를 둔다(_pool, 11/19): 슬퍼하신 사진은 쉬고, 길게 이야기하신 주제는 더, 넘기신 주제는 덜.
후보가 0장이면(사진이 적은 방이 14일 안에 다 이야기함) 가장 오래전에 이야기한 사진을 다시 고른다.
INSERT … ON CONFLICT (room_id, pick_date) DO NOTHING 이라 잡과 지연 보정(D9)이 동시에 돌아도 하루 1장.
"""

from __future__ import annotations

import random
from collections import Counter, defaultdict
from datetime import date, datetime, time, timedelta
from statistics import mean

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.ai.quiz import photo_tags
from app.config import PICK_LEARN_DAYS, PICK_LIKE, TZ
from app.models import ELDER_SPOKE, DailyPick, Photo, TalkSession


def today_pick(db: Session, room_id: int, today: date) -> DailyPick | None:
    return db.scalar(select(DailyPick).where(DailyPick.room_id == room_id, DailyPick.pick_date == today))


def _pool(db: Session, room_id: int, candidates: list[int], today: date) -> list[int]:
    """후보를 뽑힐 무게만큼 되풀이한 목록 (11/19 돌봄 루프 — 어르신 반응을 다음 사진 고르기에).

    - 그 사진으로 이야기하다 많이 슬퍼하시거나 위급 신호가 났으면(최근 PICK_LEARN_DAYS 일) 뺀다 — 쉬게 한다
    - 평소보다 길게 이야기하신 주제(활동·주제 이름표)의 사진은 4칸, 두 번 넘게 넘기신 주제는 1칸, 나머지는 2칸
    쉬게 할 사진을 빼고 남는 것이 없으면 후보 그대로(비우지 않는다). 새 주제도 늘 2칸은 있어 계속 섞여 나온다.
    """
    since = today - timedelta(days=PICK_LEARN_DAYS)
    photos = db.scalars(select(Photo).where(Photo.room_id == room_id, Photo.status == "ACTIVE"))
    tags = {p.photo_id: next((tag for tag in photo_tags(p) if tag), None) for p in photos}
    talks = db.execute(
        select(TalkSession.photo_id, TalkSession.emotion_flag, TalkSession.turns).where(
            TalkSession.room_id == room_id,
            TalkSession.kind == "MEMORY",
            TalkSession.photo_id.is_not(None),
            TalkSession.started_at >= datetime.combine(since, time.min, tzinfo=TZ),
            ELDER_SPOKE,
        )
    ).all()
    rest = {
        photo_id
        for photo_id, flag, turns in talks
        if flag == "RISK" or any(turn.get("signal") == "SAD" for turn in turns)
    }
    words: dict[str, list[int]] = defaultdict(list)
    for photo_id, _, turns in talks:
        if tags.get(photo_id):
            said = [str(turn.get("text", "")) for turn in turns if turn.get("speaker") == "ELDER"]
            words[tags[photo_id]].append(sum(len(text.split()) for text in said))
    every = [n for counts in words.values() for n in counts]
    # 주제 하나의 대화가 두 번은 쌓여야 '좋아하신다'고 본다 (한 번의 긴 대화로 쏠리지 않게)
    liked = {tag for tag, counts in words.items() if len(counts) >= 2 and mean(counts) > mean(every) * PICK_LIKE}
    skips = Counter(
        tags.get(photo_id)
        for photo_id in db.scalars(
            select(DailyPick.photo_id).where(
                DailyPick.room_id == room_id, DailyPick.status == "SKIPPED", DailyPick.pick_date >= since
            )
        )
    )

    def weight(photo_id: int) -> int:
        tag = tags.get(photo_id)
        return 4 if tag in liked else 1 if tag and skips[tag] >= 2 else 2

    return [p for p in candidates if p not in rest for _ in range(weight(p))] or list(candidates)


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
        photo_id = random.choice(_pool(db, room_id, candidates, today))
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
