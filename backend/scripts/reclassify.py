"""옛 판으로 분류된 활성 가족 사진의 analyzed_at만 비워 다음 예약 분류 대상으로 돌린다 (D76)."""

import argparse

from sqlalchemy import func, or_, select, update
from sqlalchemy.orm import Session

from app.ai.classify import PROMPT_VERSION
from app.config import CLASSIFY_PER_DAY, settings
from app.db import SessionLocal
from app.models import Photo


def reset(db: Session, room_id: int | None = None, dry_run: bool = False) -> int:
    """대상 수를 반환한다. dry_run은 저장하지 않고, 실제 실행도 분류·가족 정정값을 보존한다."""
    version = f"{settings.LLM_MODEL}/{PROMPT_VERSION}"[:30]
    conditions = [
        Photo.source == "FAMILY",
        Photo.status == "ACTIVE",
        Photo.analyzed_at.is_not(None),
        or_(Photo.model_version.is_(None), Photo.model_version != version),
    ]
    if room_id is not None:
        conditions.append(Photo.room_id == room_id)
    if dry_run:
        return db.scalar(select(func.count()).select_from(Photo).where(*conditions))
    result = db.execute(update(Photo).where(*conditions).values(analyzed_at=None))
    db.commit()
    return result.rowcount


def main() -> None:
    parser = argparse.ArgumentParser(description="옛 판으로 분류된 활성 가족 사진을 재분류 대기로 돌립니다.")
    parser.add_argument("--room-id", type=int)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    if not settings.is_dev and not args.force:
        parser.exit(1, "APP_ENV=deploy에서는 --force를 붙여야 실행할 수 있어요\n")
    with SessionLocal() as db:
        count = reset(db, args.room_id, args.dry_run)
    print(f"방: {args.room_id if args.room_id is not None else '전체'}")
    print(f"{'대상 수' if args.dry_run else '바꾼 수'}: {count}")
    if count > CLASSIFY_PER_DAY:
        print("하루 상한이라 며칠에 나눠 분류돼요")


if __name__ == "__main__":
    main()
