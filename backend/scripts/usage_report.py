"""KST 날짜 범위의 사용 지표만 집계한다. 글·이름·사진 설명은 읽거나 출력하지 않는다 (D12·D15)."""

import argparse
from datetime import date, datetime, time, timedelta

from sqlalchemy import Date, cast, func, select
from sqlalchemy.orm import Session

from app.config import TZ
from app.db import SessionLocal
from app.models import ELDER_SPOKE, DailyPick, Diary, FamilyRoom, MoodCheck, TalkSession


def report(db: Session, room_id: int, start: date, end: date) -> dict:
    """시작일·종료일을 모두 포함한다. 완료 비율은 전체 대화 중 COMPLETED·LIMIT의 비율(0~1)."""
    if start > end:
        raise ValueError("시작 날짜는 끝 날짜보다 늦을 수 없어요")
    since = datetime.combine(start, time.min, tzinfo=TZ)
    until = datetime.combine(end + timedelta(days=1), time.min, tzinfo=TZ)
    out = {"room_id": room_id, "from": start.isoformat(), "to": end.isoformat()}
    pick_counts = dict(
        db.execute(
            select(DailyPick.status, func.count())
            .where(
                DailyPick.room_id == room_id,
                DailyPick.pick_date >= start,
                DailyPick.pick_date <= end,
            )
            .group_by(DailyPick.status)
        ).all()
    )
    for status in ("COMPLETED", "SKIPPED", "EXPIRED", "PENDING"):
        out[f"picks_{status.lower()}"] = pick_counts.get(status, 0)
    talks = (TalkSession.room_id == room_id, TalkSession.started_at >= since, TalkSession.started_at < until)
    for kind in ("MEMORY", "ALBUM", "DIARY"):
        out[f"sessions_{kind.lower()}"] = db.scalar(
            select(func.count())
            .select_from(TalkSession)
            .where(
                *talks,
                TalkSession.kind == kind,
            )
        )
    for reason in ("COMPLETED", "LIMIT", "USER_STOP", "NO_RESPONSE", "ERROR"):
        out[f"ended_{reason.lower()}"] = db.scalar(
            select(func.count())
            .select_from(TalkSession)
            .where(
                *talks,
                TalkSession.end_reason == reason,
            )
        )
    out["unfinished"] = db.scalar(
        select(func.count())
        .select_from(TalkSession)
        .where(
            *talks,
            TalkSession.end_reason.is_(None),
        )
    )
    total, turn_avg, duration_avg, spoke, days = db.execute(
        select(
            func.count(),
            func.avg(TalkSession.turn_count),
            func.avg(TalkSession.duration_sec),
            func.count().filter(ELDER_SPOKE),
            func.count(func.distinct(cast(func.timezone("Asia/Seoul", TalkSession.started_at), Date))).filter(
                ELDER_SPOKE
            ),
        ).where(*talks)
    ).one()
    out.update(
        sessions_total=total,
        completion_rate=(out["ended_completed"] + out["ended_limit"]) / total if total else 0,
        avg_turn_count=float(turn_avg or 0),
        avg_duration_sec=float(duration_avg or 0),
        elder_spoke_sessions=spoke,
        talked_days=days,
    )
    diaries = (Diary.room_id == room_id, Diary.status == "POSTED", Diary.posted_at >= since, Diary.posted_at < until)
    for author in ("ELDER", "FAMILY"):
        out[f"diaries_{author.lower()}"] = db.scalar(
            select(func.count())
            .select_from(Diary)
            .where(
                *diaries,
                Diary.author_type == author,
            )
        )
    out["family_diaries_read"] = db.scalar(
        select(func.count())
        .select_from(Diary)
        .where(
            *diaries,
            Diary.author_type == "FAMILY",
            Diary.elder_read_at.is_not(None),
        )
    )
    out["family_diary_read_rate"] = out["family_diaries_read"] / out["diaries_family"] if out["diaries_family"] else 0
    diary_day = cast(func.timezone("Asia/Seoul", Diary.posted_at), Date)
    out["diary_days"] = db.scalar(select(func.count(func.distinct(diary_day))).where(*diaries))
    out["elder_diary_days"] = db.scalar(
        select(func.count(func.distinct(diary_day))).where(
            *diaries,
            Diary.author_type == "ELDER",
        )
    )
    out["mood_checks"] = db.scalar(
        select(func.count())
        .select_from(MoodCheck)
        .where(
            MoodCheck.room_id == room_id,
            MoodCheck.check_date >= start,
            MoodCheck.check_date <= end,
        )
    )
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description="가족방 사용 지표를 KST 날짜 기준으로 집계합니다.")
    parser.add_argument("--room-id", type=int)
    parser.add_argument("--from", dest="start", type=date.fromisoformat, required=True)
    parser.add_argument("--to", dest="end", type=date.fromisoformat, required=True)
    args = parser.parse_args()
    if args.start > args.end:
        parser.error("시작 날짜는 끝 날짜보다 늦을 수 없어요")
    with SessionLocal() as db:
        room_ids = db.scalars(
            select(FamilyRoom.room_id)
            .where(
                FamilyRoom.status == "ACTIVE",
                *([FamilyRoom.room_id == args.room_id] if args.room_id is not None else []),
            )
            .order_by(FamilyRoom.room_id)
        ).all()
        if not room_ids:
            parser.exit(1, "집계할 활성 가족방이 없어요\n")
        for room_id in room_ids:
            print("metric                         | value")
            print("-------------------------------|---------------------")
            for metric, value in report(db, room_id, args.start, args.end).items():
                print(f"{metric:30} | {value}")


if __name__ == "__main__":
    main()
