"""개발 DB 초기화 + 시드. backend 폴더에서:  uv run python -m scripts.seed

순서: public 스키마 비움 → db/schema.sql → db/seed/seed.sql → 사진 파일 3장 생성(uploads/) → data/question_bank.json
→ 오늘의 한 장 1행(한국 날짜). 기존 데이터는 전부 지워진다. 배포 DB(APP_ENV=deploy)는 --force 없이는 거부.
테스트 계정·어르신 연결 링크는 db/seed/seed.sql 머리 주석과 README 에 있다.
"""

from __future__ import annotations

import io
import json
import sys

from PIL import Image, ImageDraw
from sqlalchemy import select

from app.config import ROOT, settings, today_kst
from app.db import SessionLocal, engine
from app.models import DailyPick, FamilyRoom, Photo, QuestionBank
from app.services import storage

COLORS = [(222, 184, 135), (143, 188, 143), (176, 196, 222)]


def placeholder_jpeg(index: int, caption: str) -> bytes:
    img = Image.new("RGB", (800, 600), COLORS[index % len(COLORS)])
    draw = ImageDraw.Draw(img)
    draw.rectangle((40, 40, 760, 560), outline=(255, 255, 255), width=6)
    draw.text((60, 60), f"seed photo {index}", fill=(40, 40, 40))  # 기본 폰트(ASCII) — 한글은 캡션 컬럼에만
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=80)
    return buf.getvalue()


def main() -> None:
    if not settings.is_dev and "--force" not in sys.argv:
        sys.exit("APP_ENV=deploy 에서는 데이터가 전부 지워지므로 --force 를 붙여야 합니다")
    with engine.begin() as conn:
        conn.exec_driver_sql("DROP SCHEMA public CASCADE; CREATE SCHEMA public;")
        conn.exec_driver_sql((ROOT / "db" / "schema.sql").read_text("utf-8"))
        conn.exec_driver_sql((ROOT / "db" / "seed" / "seed.sql").read_text("utf-8"))
    with SessionLocal() as db:
        photos = db.scalars(select(Photo).order_by(Photo.photo_id)).all()
        for i, p in enumerate(photos):
            storage.put(p.object_key, placeholder_jpeg(i, p.caption or ""))
        bank = json.loads((ROOT / "data" / "question_bank.json").read_text("utf-8"))["questions"]
        for q in bank:
            db.add(QuestionBank(**q, created_by="seed"))
        room = db.scalar(select(FamilyRoom).order_by(FamilyRoom.room_id))
        db.add(DailyPick(room_id=room.room_id, pick_date=today_kst(), photo_id=photos[0].photo_id))
        db.commit()
    print(
        f"시드 완료: 가족방 1, 가족 2, 사진 {len(photos)}, 문제 {len(bank)}, 오늘의 한 장 1 ({today_kst()})\n"
        "  가족 로그인: test@haru.local / test1234\n"
        "  어르신 연결 링크: http://localhost:5173/elder/connect#seed-elder-link-token-only-for-dev-0001"
    )


if __name__ == "__main__":
    main()
