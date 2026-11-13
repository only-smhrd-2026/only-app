"""가족 일기 동무 — 가족이 쓴 몇 마디 → AI 질문 1개 → 답 → 존댓말 1인칭 초안 (FR-DI-006·007, AI-06 #45, D58).

화면 FDIARY_002(질문)·FDIARY_003(초안 고치기)이 부른다. 서버는 아무것도 저장하지 않는다: 초안은 화면이 들고 있다가
가족이 고친 뒤 POST /rooms/{id}/diaries(routers/diaries.py)로 올린다.
여러 가족방에 보내도 질문·초안은 고른 방 하나로 한 번만 부른다.
Claude 는 어르신 대화와 같은 서버 전체 하루 상한(D46 ⑨)을 쓰고, 넘거나 실패하면 고정 질문·쓴 말 그대로의 초안.
로그에 가족 글을 남기지 않는다 (D15).
"""

from fastapi import APIRouter

from app.ai import coach
from app.deps import DB, CurrentUser, require_member
from app.errors import ApiError
from app.models import User
from app.schemas.family_diary import FamilyAskIn, FamilyAskOut, FamilyDraftIn, FamilyDraftOut
from app.security import family_ai_allowed

router = APIRouter(prefix="/rooms/{room_id}/family-diary", tags=["family-diary"])


def _check(room_id: int, user: User, db) -> None:
    require_member(room_id, user, db)  # 로그인 안 함 401(CurrentUser), 남의 가족방 404 (D43)
    if not family_ai_allowed(user.user_id):  # 구성원 확인 뒤에 센다 — 남의 방 번호로는 횟수도 안 쓴다
        raise ApiError(429, "TOO_MANY_REQUESTS", "잠시 뒤에 다시 해 주세요")


@router.post("/ask", response_model=FamilyAskOut)
def ask(room_id: int, body: FamilyAskIn, user: CurrentUser, db: DB):
    """가족이 쓴 말 → 일기 동무 질문 1개 (FR-DI-006). 실패하면 고정 질문."""
    _check(room_id, user, db)
    return FamilyAskOut(question=coach.family_question(body.text))


@router.post("/draft", response_model=FamilyDraftOut)
def draft(room_id: int, body: FamilyDraftIn, user: CurrentUser, db: DB):
    """쓴 말 + 질문 + 답 → 존댓말 1인칭 초안 (FR-DI-007). 실패하면 쓴 말·답을 그대로 이은 글."""
    _check(room_id, user, db)
    return FamilyDraftOut(body=coach.family_draft(body.text, body.question, body.answer))
