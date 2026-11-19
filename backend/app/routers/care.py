"""가족 홈 돌봄 일지 (11/18 멘토링 — 돌봄 루프). GET /rooms/{room_id}/care — 최근 7일 가운데 살핀 것이 있는 날."""

from fastapi import APIRouter

from app.deps import DB, CurrentUser, require_member
from app.schemas.care import CareOut
from app.services import care

router = APIRouter(prefix="/rooms/{room_id}", tags=["care"])


@router.get("/care", response_model=CareOut)
def get_care(room_id: int, user: CurrentUser, db: DB):
    require_member(room_id, user, db)
    days = care.journal(db, room_id)
    db.commit()  # 오늘 줄이 없었으면 journal 이 만든다
    return CareOut(days=days)
