"""기존 기록을 보존하며 시연용 지난 기록을 넣는다. backend에서 python -m scripts.demo_data --room-id 1."""

import argparse
import uuid
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.config import TZ, now_kst, settings
from app.db import SessionLocal
from app.models import Diary, FamilyRoom, MoodCheck, TalkSession, WeeklySummary
from app.services import weekly


def fill(db: Session, room_id: int, now: datetime) -> dict[str, int]:
    """같은 방·날짜에는 같은 번호를 사용한다. 기존 줄은 변경하지 않는다."""
    room = db.get(FamilyRoom, room_id)
    if room is None or room.status != "ACTIVE":
        raise ValueError("가족방이 없거나 닫혀 있어 시연 자료를 넣지 않았어요")
    now = now.astimezone(TZ)
    counts = {"sessions": 0, "diaries": 0, "mood_checks": 0, "weekly_summaries": 0}

    def key(kind, day):
        return uuid.uuid5(uuid.NAMESPACE_URL, f"haru-demo:{room_id}:{kind}:{day.isoformat()}")

    for offset in range(1, 6):
        at = (now - timedelta(days=offset)).replace(hour=10, minute=0, second=0, microsecond=0)
        turns = [
            {
                "turn_no": 1,
                "speaker": "AI",
                "text": "사진을 보니 어떤 기억이 떠오르세요?",
                "created_at": at.isoformat(),
            },
            {
                "turn_no": 2,
                "speaker": "ELDER",
                "text": "마당에서 가족과 꽃을 가꾸던 기억이 나요",
                "created_at": (at + timedelta(seconds=10)).isoformat(),
            },
        ]
        counts["sessions"] += (
            db.execute(
                pg_insert(TalkSession)
                .values(
                    session_id=key("talk", at.date()),
                    room_id=room_id,
                    kind="MEMORY",
                    input_mode="VOICE",
                    started_at=at,
                    ended_at=at + timedelta(minutes=2),
                    end_reason="COMPLETED",
                    turn_count=2,
                    duration_sec=120,
                    emotion_flag="LOW" if offset == 3 else "NONE",
                    turns=turns,
                )
                .on_conflict_do_nothing()
                .returning(TalkSession.session_id)
            ).scalar_one_or_none()
            is not None
        )
    for offset, mood in enumerate(("GOOD", "SO_SO", "UPSET", "LONELY"), 1):
        at = (now - timedelta(days=offset)).replace(hour=18, minute=0, second=0, microsecond=0)
        counts["diaries"] += (
            db.execute(
                pg_insert(Diary)
                .values(
                    room_id=room_id,
                    author_type="ELDER",
                    body="오늘은 동네를 천천히 산책했어요.",
                    mood=mood,
                    illustration_type="NONE",
                    request_id=key("diary", at.date()),
                    posted_at=at,
                )
                .on_conflict_do_nothing()
                .returning(Diary.diary_id)
            ).scalar_one_or_none()
            is not None
        )
    day = (now - timedelta(days=10)).date()
    counts["mood_checks"] += (
        db.execute(
            pg_insert(MoodCheck)
            .values(
                room_id=room_id,
                check_date=day,
                answers=[0] * 8,
                total=0,
                level="USUAL",
                created_at=now - timedelta(days=10),
            )
            .on_conflict_do_nothing()
            .returning(MoodCheck.check_id)
        ).scalar_one_or_none()
        is not None
    )
    db.commit()
    week = weekly.window(now)[2]
    before = db.scalar(
        select(WeeklySummary.summary_id).where(
            WeeklySummary.room_id == room_id,
            WeeklySummary.week_start == week,
        )
    )
    weekly.build(db, room_id, now)
    counts["weekly_summaries"] = int(before is None)
    return counts


def main() -> None:
    parser = argparse.ArgumentParser(description="기존 자료를 보존하며 시연용 지난 기록을 넣습니다.")
    parser.add_argument("--room-id", type=int, required=True)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    if not settings.is_dev and not args.force:
        parser.exit(1, "APP_ENV=deploy에서는 --force를 붙여야 시연 자료를 넣을 수 있어요\n")
    now = now_kst()
    with SessionLocal() as db:
        try:
            counts = fill(db, args.room_id, now)
        except ValueError as exc:
            parser.exit(1, f"{exc}\n")
    print(f"방 {args.room_id} 날짜 {now.date()}")
    for kind, count in counts.items():
        print(f"{kind}: {count}")


if __name__ == "__main__":
    main()
