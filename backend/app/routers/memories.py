"""회상 카드 API (D115, 11/27 팀 회의) — 가족 홈 피드에 어르신 회상(사진 보며 나눈 이야기)을 일기와 섞어 보여 준다.

- GET  /rooms/{room_id}/memories            최근 MEMORY_FEED_DAYS 일(한국 날짜, 오늘 포함)의 회상 카드, 새것 먼저
- POST /memories/{session_id}/reaction      좋아요(하트 하나) {kind: HEART, on}
- POST·PATCH·DELETE /memories/{session_id}/reply   댓글 남기기·고치기·지우기
  — 일기 댓글과 같은 규칙(한 사람 여러 개, 200자)

카드는 요약(sessions.family_summary)이 만들어진 대화만(ai/memory_card). 사진을 지웠으면 카드도 안 보인다.
남의 가족방 대화는 있는지도 모르게 404 (D43). 댓글 글은 로그에 남기지 않는다 (D15).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta

from fastapi import APIRouter
from sqlalchemy import func, select

from app.config import MEMORY_FEED_DAYS, TZ, now_kst, today_kst
from app.deps import DB, CurrentUser, require_member
from app.errors import ApiError
from app.models import Photo, RoomMember, TalkSession
from app.routers.diaries import _member_names
from app.schemas.diaries import MemoryCardOut, MemoryListOut, MemoryReactionIn, ReplyEditIn, ReplyIn

router = APIRouter(tags=["memories"])

_SHOWN = (
    TalkSession.kind.in_(["MEMORY", "ALBUM"]),
    TalkSession.family_summary.is_not(None),
    TalkSession.family_summary != "",
    Photo.status == "ACTIVE",
)


def _cards(db, room_id: int, *cond) -> list[MemoryCardOut]:
    rows = db.execute(
        select(TalkSession, Photo.object_key)
        .join(Photo, Photo.photo_id == TalkSession.photo_id)
        .where(TalkSession.room_id == room_id, *_SHOWN, *cond)
        .order_by(func.coalesce(TalkSession.ended_at, TalkSession.started_at).desc())
    ).all()
    names = _member_names(db, room_id, full=True) if any(s.reactions for s, _ in rows) else {}
    return [
        MemoryCardOut(
            session_id=s.session_id,
            room_id=s.room_id,
            photo_url=f"/api/media/{key}",
            summary=s.family_summary,
            ended_at=s.ended_at or s.started_at,
            # 좋아요 칸 먼저, 댓글은 남긴 순서 — 일기(diaries._rows)와 같은 차례
            reactions=[
                dict(r, name=names.get(r.get("user_id")))
                for r in sorted(s.reactions, key=lambda r: r.get("kind") == "REPLY")
            ],
        )
        for s, key in rows
    ]


@router.get("/rooms/{room_id}/memories", response_model=MemoryListOut)
def list_memories(room_id: int, user: CurrentUser, db: DB):
    require_member(room_id, user, db)
    since = datetime.combine(today_kst() - timedelta(days=MEMORY_FEED_DAYS - 1), datetime.min.time(), tzinfo=TZ)
    return MemoryListOut(memories=_cards(db, room_id, TalkSession.started_at >= since))


def _locked(db, session_id: uuid.UUID, user) -> TalkSession:
    """좋아요·댓글을 바꿀 회상 대화를 행 잠금으로 읽는다 — 두 가족이 동시에 눌러도 서로의 칸을 덮어쓰지 않게."""
    s = db.get(TalkSession, session_id, with_for_update=True)
    member = s is not None and db.scalar(
        select(RoomMember.member_id).where(
            RoomMember.room_id == s.room_id,
            RoomMember.user_id == user.user_id,
            RoomMember.removed_at.is_(None),
        )
    )
    if not member or s.kind not in ("MEMORY", "ALBUM") or not s.family_summary:
        raise ApiError(404, "MEMORY_NOT_FOUND", "회상 카드를 찾을 수 없어요")
    return s


def _out(db, s: TalkSession) -> MemoryCardOut:
    session_id, room_id = s.session_id, s.room_id
    db.commit()  # 바뀐 게 없어도 — 행 잠금이 풀린다
    cards = _cards(db, room_id, TalkSession.session_id == session_id)
    if not cards:  # 그사이 사진이 지워졌다
        raise ApiError(404, "MEMORY_NOT_FOUND", "회상 카드를 찾을 수 없어요")
    return cards[0]


def _mine(s: TalkSession, user_id: int, reply: bool) -> list[dict]:
    """이 가족의 좋아요 칸(reply=False) 또는 댓글 칸들(reply=True), 남긴 순서."""
    return [r for r in s.reactions if r.get("user_id") == user_id and (r.get("kind") == "REPLY") == reply]


@router.get("/memories/{session_id}", response_model=MemoryCardOut)
def get_memory(session_id: uuid.UUID, user: CurrentUser, db: DB):
    """회상 카드 한 장 — 가족 홈 💬 로 여는 회상 상세(댓글 화면, 11/27). 남의 방·없는 카드는 404"""
    return _out(db, _locked(db, session_id, user))


@router.post("/memories/{session_id}/reaction", response_model=MemoryCardOut)
def memory_like(session_id: uuid.UUID, body: MemoryReactionIn, user: CurrentUser, db: DB):
    """좋아요 켜기·끄기 — 한 사람 1칸. 같은 요청이 두 번 와도 결과가 같다."""
    s = _locked(db, session_id, user)
    liked = _mine(s, user.user_id, reply=False)
    if body.on and not liked:  # 새 리스트를 통째로 넣어야 저장된다
        new = {"by": "FAMILY", "user_id": user.user_id, "kind": "HEART", "at": now_kst().isoformat()}
        s.reactions = [*s.reactions, new]
    elif not body.on and liked:
        s.reactions = [r for r in s.reactions if not any(r is m for m in liked)]
    return _out(db, s)


@router.post("/memories/{session_id}/reply", response_model=MemoryCardOut)
def memory_reply(session_id: uuid.UUID, body: ReplyIn, user: CurrentUser, db: DB):
    """댓글 남기기 — 보낼 때마다 새 칸. 내 바로 앞 댓글과 같은 글이 또 오면(두 번 누름) 그대로 둔다."""
    s = _locked(db, session_id, user)
    last = _mine(s, user.user_id, reply=True)[-1:]
    if not last or last[0].get("text") != body.text:
        new = {"by": "FAMILY", "user_id": user.user_id, "kind": "REPLY", "text": body.text, "at": now_kst().isoformat()}
        s.reactions = [*s.reactions, new]
    return _out(db, s)


@router.patch("/memories/{session_id}/reply", response_model=MemoryCardOut)
def memory_reply_edit(session_id: uuid.UUID, body: ReplyEditIn, user: CurrentUser, db: DB):
    """내 댓글 고치기 — body.at 그 칸의 시각(응답의 at 그대로). at 은 그대로 둔다."""
    s = _locked(db, session_id, user)
    cell = next((r for r in _mine(s, user.user_id, reply=True) if r.get("at") == body.at), None)
    if cell is None:
        raise ApiError(404, "REPLY_NOT_FOUND", "고칠 댓글을 찾을 수 없어요")
    s.reactions = [r | {"text": body.text} if r is cell else r for r in s.reactions]
    return _out(db, s)


@router.delete("/memories/{session_id}/reply", status_code=204)
def memory_reply_delete(session_id: uuid.UUID, user: CurrentUser, db: DB, at: str | None = None):
    """내 댓글 하나 지우기 — ?at= 그 칸의 시각. 없어도 204. at 이 없으면 내 댓글을 모두 지운다(일기 댓글과 같게)."""
    s = _locked(db, session_id, user)
    gone = [r for r in _mine(s, user.user_id, reply=True) if at is None or r.get("at") == at]
    if gone:
        s.reactions = [r for r in s.reactions if not any(r is g for g in gone)]
    db.commit()
