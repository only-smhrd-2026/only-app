"""회원 탈퇴 (POST /api/auth/withdraw). 되돌릴 수 없어서 지금 비밀번호를 다시 받는다.

- 계정 줄은 남기고(남은 글·사진이 가리킴) 이메일·비밀번호·이름을 바로 지운다 → 이름은 '탈퇴한 가족'.
  같은 이메일로 다시 가입하면 새 계정이다. 이미 발급된 쿠키는 deps._user_from_cookie 가 status 를 봐서 401.
- 내가 쓴 가족 일기·올린 사진은 가족방에 '탈퇴한 가족' 이름으로 남는다 (가족방 나가기와 같은 규칙).
- 내가 방장인 가족방: 다른 가족이 있으면 방장을 넘기고, 혼자면 가족방과 어르신 기록을 전부 지운다.
  어느 쪽인지 화면이 보여 준 그대로 보내야 한다(transfers) — 그사이 구성원이 바뀌었으면 아무것도 바꾸지 않고 400.
"""

import logging
from datetime import timedelta

from fastapi import APIRouter, Request, Response
from sqlalchemy import delete, select, update

from app.config import WITHDRAW_REAUTH_MIN, now_kst
from app.deps import DB, CurrentUser
from app.errors import ApiError
from app.models import (
    CareDay,
    DailyPick,
    Diary,
    FamilyRoom,
    GroupVocab,
    MoodCheck,
    Notification,
    Photo,
    PushSubscription,
    RoomMember,
    StoryFact,
    TalkSession,
    UrgentAlert,
    WeeklySummary,
)
from app.schemas.account import WithdrawIn
from app.schemas.common import OkOut
from app.security import (
    SESSION_COOKIE,
    clear_cookie,
    clear_login_failures,
    login_allowed,
    reserve_login_attempt,
    verify_password,
)
from app.services import storage

log = logging.getLogger("app.account")
router = APIRouter(prefix="/auth", tags=["auth"])

WITHDRAWN_NAME = "탈퇴한 가족"  # 남은 일기의 글쓴이 이름 (users.name)
# 가족방 하나를 통째로 지우는 순서 — db/schema.sql 의 FK 를 따라, 가리키는 표부터. family_rooms 는 맨 끝에 따로.
# room_id 칸이 있는 표가 늘면 여기에도 넣는다 (빠뜨리면 tests/test_withdraw.py 가 잡는다)
_ROOM_TABLES = (
    PushSubscription,  # 어르신 기기의 푸시 구독
    CareDay,
    UrgentAlert,  # → sessions, users(acked_by 는 계정 줄이 남아 그대로)
    Notification,
    MoodCheck,
    WeeklySummary,
    GroupVocab,
    RoomMember,
    StoryFact,  # → sessions
    Diary,  # → sessions, photos
    TalkSession,  # → daily_picks, photos
    DailyPick,  # → photos
    Photo,
)


def _delete_room(db, room_id: int) -> list[str]:
    """가족방과 딸린 줄을 전부 지운다(커밋은 부른 쪽). 커밋 뒤에 지울 저장소 파일 key 를 돌려준다."""
    keys = [
        k for row in db.execute(select(Photo.object_key, Photo.thumb_key).where(Photo.room_id == room_id)) for k in row
    ]
    keys += db.scalars(select(Diary.illustration_key).where(Diary.room_id == room_id))
    # 가족 목소리 답장 소리 (D99) — 일기 반응 칸에 key 가 있다
    cells = db.scalars(select(Diary.reactions).where(Diary.room_id == room_id))
    keys += [r["audio_key"] for reactions in cells for r in reactions if r.get("audio_key")]
    keys.append(db.scalar(select(FamilyRoom.elder_photo_key).where(FamilyRoom.room_id == room_id)))  # 어르신 얼굴 사진
    # 그림일기 그림은 올리지 않은 초안의 것도 저장소에 남아 있다 (diaries._draw — 일기 대화마다 key 가 정해져 있다)
    diary_talks = select(TalkSession.session_id).where(TalkSession.room_id == room_id, TalkSession.kind == "DIARY")
    keys += [f"rooms/{room_id}/{session_id}.jpg" for session_id in db.scalars(diary_talks)]
    # daily_picks 와 sessions 는 서로를 가리킨다 → 한쪽 칸을 먼저 비운다
    db.execute(update(DailyPick).where(DailyPick.room_id == room_id).values(completed_session_id=None))
    for table in _ROOM_TABLES:
        db.execute(delete(table).where(table.room_id == room_id))
    db.execute(delete(FamilyRoom).where(FamilyRoom.room_id == room_id))
    return [k for k in dict.fromkeys(keys) if k]


@router.post("/withdraw", response_model=OkOut)
def withdraw(body: WithdrawIn, request: Request, response: Response, user: CurrentUser, db: DB):
    # 비밀번호 확인 — 비밀번호 바꾸기(auth.change_password)와 같은 오류 코드·같은 실패 제한
    ip = request.client.host if request.client else "unknown"
    email = user.email
    if user.password_hash is None:
        # 다시 확인할 비밀번호가 없으니 '방금 카카오로 로그인했는지'로 갈음한다 — 오래된 로그인 쿠키(잃어버린 폰·
        # 같이 쓰는 폰)만으로는 가족방을 지울 수 없게 (11/19 보안 점검)
        fresh = user.last_login_at or user.created_at
        if now_kst() - fresh > timedelta(minutes=WITHDRAW_REAUTH_MIN):
            raise ApiError(403, "REAUTH_REQUIRED", "안전을 위해 카카오로 다시 로그인한 뒤 바로 탈퇴해 주세요")
    else:
        # 이메일별 시도 칸을 비교 전에 먼저 잡는다(로그인과 같은 셈·같은 방식, security.reserve_login_attempt)
        if not login_allowed(ip) or (email and not reserve_login_attempt(email)):
            raise ApiError(429, "TOO_MANY_ATTEMPTS", "잠시 후 다시 시도해 주세요")
        if not verify_password(body.password, user.password_hash):
            raise ApiError(400, "WRONG_PASSWORD", "지금 비밀번호가 맞지 않아요")  # 잡은 칸이 실패로 남는다
        if email:
            clear_login_failures(email)  # 비밀번호는 맞았다 — 아래에서 거절돼도(방장 넘기기 등) 실패가 아니다

    transfers = {t.room_id: t.new_owner_user_id for t in body.transfers}
    keys: list[str] = []
    rooms_deleted = 0
    # 내가 방장인 가족방. 줄을 잠가 그사이 새 가족이 들어오거나 새 글이 쌓이지 않게 한다.
    # 잠그는 순서는 가족방 → 구성원 → 계정. 계정을 먼저 잠그면 내게 알림을 넣는 요청(어르신 일기 올리기)과 서로 기다린다
    owned = db.scalars(
        select(FamilyRoom)
        .where(FamilyRoom.owner_user_id == user.user_id)
        .order_by(FamilyRoom.room_id)
        .with_for_update()
    ).all()
    for room in owned:
        # 다른 활동 구성원. 잠가 두면 넘겨받을 사람이 그사이 나가지 못한다 (rooms.leave_room 도 이 줄을 잠근다)
        others = set(
            db.scalars(
                select(RoomMember.user_id)
                .where(
                    RoomMember.room_id == room.room_id,
                    RoomMember.user_id != user.user_id,
                    RoomMember.removed_at.is_(None),
                )
                .with_for_update()
            )
        )
        target = transfers.get(room.room_id)
        name = f"{room.elder_name} {room.elder_honorific}네 가족방"
        if others:
            if target not in others:
                raise ApiError(400, "OWNER_TRANSFER_REQUIRED", f"{name}의 방장을 넘길 분을 골라 주세요")
            room.owner_user_id = target
        elif room.room_id not in transfers or target is not None:
            # 화면이 '지워져요'를 보여 준 방만 지운다 — 넘기려던 분이 그사이 나가 혼자가 된 방을 말없이 지우지 않는다
            raise ApiError(
                400,
                "ROOM_DELETE_CONFIRM_REQUIRED",
                f"{name}에 다른 가족이 없어요. 탈퇴하면 이 가족방이 지워지니 다시 확인해 주세요",
            )
        else:
            keys += _delete_room(db, room.room_id)
            rooms_deleted += 1

    # 내 목소리 답장(D99)은 탈퇴하면 칸과 소리를 지운다 — 글 한마디·이모지는 지금처럼 남는다 (11/24 사용자: 보관은
    # 답장이 있는 동안). 지운 가족방의 일기는 위에서 이미 없어졌다
    voiced = db.scalars(
        select(Diary)
        .where(Diary.reactions.contains([{"by": "FAMILY", "user_id": user.user_id, "kind": "REPLY"}]))
        .with_for_update()
    ).all()
    for diary in voiced:
        mine = [r for r in diary.reactions if r.get("user_id") == user.user_id and r.get("audio_key")]
        if mine:
            keys += [r["audio_key"] for r in mine]
            diary.reactions = [r for r in diary.reactions if r not in mine]
    # 방장이 아닌 가족방은 나가기와 같게 구성원 줄을 지운다 (rooms.leave_room). 방장을 넘긴 방·내보내진 방(removed_at)의
    # 줄도 지운다 — 줄이 남으면 남은 글 옆에 호칭이 그대로 보인다
    db.execute(delete(RoomMember).where(RoomMember.user_id == user.user_id))
    db.execute(delete(Notification).where(Notification.target_user_id == user.user_id))
    db.execute(delete(PushSubscription).where(PushSubscription.user_id == user.user_id))  # 내 폰의 푸시 구독
    if user.profile_key:
        keys.append(user.profile_key)
    user.status = "WITHDRAWN"
    user.name = WITHDRAWN_NAME
    user.email = user.password_hash = user.kakao_id = user.profile_key = None
    db.commit()
    clear_cookie(response, SESSION_COOKIE)
    if email:
        clear_login_failures(email)  # 같은 이메일로 다시 가입한 새 계정이 옛 실패 횟수를 물려받지 않게

    # 파일은 DB 저장 뒤에 지운다 (photos.commit_photo_deletion 과 같은 순서). 실패해도 탈퇴는 그대로, 로그는 수만 (D15)
    # ponytail: 요청 안에서 하나씩 지운다 — R2 는 파일마다 왕복이라 사진 수백 장이면 십몇 초. 느리면 BackgroundTasks 로
    failed = 0
    for key in keys:
        try:
            storage.delete(key)
        except Exception:
            failed += 1
    log.info("withdraw user=%s rooms_deleted=%d files=%d failed=%d", user.user_id, rooms_deleted, len(keys), failed)
    return OkOut()
