"""회상 대화 세션 — 음성 왕복 걷는 해골 (초석 원안 D). 계약은 schemas/sessions.py.

턴 정의: AI 질문 1 + 어르신 답 1 = 1턴. sessions.turn_count = 지금까지 낸 AI 질문 수 (만들 때 1, 최대 MAX_TURNS=8).
8번째 답을 받으면 AI 가 마무리 인사(CLOSING) 를 하고 state=ENDED, end_reason=COMPLETED.
session_turns.turn_no 는 행 순번 (1=AI, 2=ELDER, 3=AI …).
서버가 지키는 상한: 8턴, 5분, 무응답 3단계, 저신뢰 2회 → input_locked (D5, D8).
"""

from __future__ import annotations

import base64
import logging
import time
import uuid
from collections import defaultdict
from datetime import timedelta

from fastapi import APIRouter
from sqlalchemy import func, select

from app.ai import coach, tts
from app.ai.schemas import CoachReply
from app.config import (
    MAX_SESSION_SEC,
    MAX_TURNS,
    NO_RESPONSE_END,
    SESSION_ERROR_ALERT,
    SESSION_RESUME_MIN,
    STT_CONF_MIN,
    STT_FAIL_LOCK,
    now_kst,
)
from app.deps import DB, CurrentDevice
from app.errors import ApiError
from app.models import DailyPick, FamilyRoom, Notification, Photo, SessionTurn, TalkSession
from app.routers.devices import notify_family
from app.schemas.sessions import (
    AiOut,
    SessionCreateIn,
    SessionEndIn,
    SessionEndOut,
    SessionGetOut,
    SessionOut,
    TurnIn,
)

log = logging.getLogger("app.sessions")
router = APIRouter(prefix="/elder/sessions", tags=["sessions"])

# ponytail: 세션별 카운터는 프로세스 메모리 (uvicorn --workers 1 전제, D9). 재시작하면 사라지지만
# 세션은 어차피 30분 지나면 ENDED 취급이라 무방. 수평 확장이 필요해지면 sessions 테이블 컬럼으로.
_no_response: dict[uuid.UUID, int] = defaultdict(int)
_low_conf: dict[uuid.UUID, int] = defaultdict(int)
_last_reply: dict[uuid.UUID, CoachReply] = {}
_tts_failed: set[uuid.UUID] = set()


def _get(db, session_id: uuid.UUID, device) -> TalkSession:
    session = db.get(TalkSession, session_id)
    if not session or session.room_id != device.room_id:
        raise ApiError(404, "SESSION_NOT_FOUND", "대화를 찾을 수 없어요")
    return session


def _turns(db, session_id: uuid.UUID) -> list[SessionTurn]:
    return db.scalars(
        select(SessionTurn).where(SessionTurn.session_id == session_id).order_by(SessionTurn.turn_no)
    ).all()


def _ctx(db, room: FamilyRoom, session: TalkSession) -> coach.CoachContext:
    photo = db.get(Photo, session.photo_id) if session.photo_id else None
    return coach.CoachContext(
        elder_name=room.elder_name,
        elder_honorific=room.elder_honorific,
        photo=(
            {
                "caption": photo.caption,
                "people_note": photo.people_note,
                "taken_at": photo.taken_at.isoformat() if photo.taken_at else None,
            }
            if photo
            else None
        ),
        turns=[{"speaker": t.speaker, "text": t.text} for t in _turns(db, session.session_id)],
    )


def _add_turn(db, session: TalkSession, speaker: str, text: str, **fields) -> SessionTurn:
    next_no = (
        db.scalar(select(func.max(SessionTurn.turn_no)).where(SessionTurn.session_id == session.session_id)) or 0
    ) + 1
    turn = SessionTurn(session_id=session.session_id, turn_no=next_no, speaker=speaker, text=text, **fields)
    db.add(turn)
    db.flush()
    return turn


def _last_ai_turn(db, session_id: uuid.UUID) -> SessionTurn | None:
    return db.scalar(
        select(SessionTurn)
        .where(SessionTurn.session_id == session_id, SessionTurn.speaker == "AI")
        .order_by(SessionTurn.turn_no.desc())
        .limit(1)
    )


def _ask(db, session: TalkSession, ctx: coach.CoachContext, closing: bool) -> CoachReply:
    """코치 호출 + AI 턴 저장 (latency_ms 기록)."""
    t0 = time.perf_counter()
    reply = coach.closing(ctx, session.turn_count) if closing else coach.next_question(ctx, session.turn_count)
    _add_turn(
        db,
        session,
        "AI",
        reply.text,
        question_type=reply.question_type,
        latency_ms=int((time.perf_counter() - t0) * 1000),
    )
    _last_reply[session.session_id] = reply
    return reply


def _ai_out(db, session: TalkSession, room: FamilyRoom, reply: CoachReply) -> AiOut:
    audio_b64 = None
    try:
        audio = tts.synthesize(reply.text, float(room.tts_speed))
        audio_b64 = base64.b64encode(audio).decode() if audio else None
    except Exception as e:  # TTS 실패 → 자막만 + 가족 알림 1건 (D5)
        log.warning("tts failed session=%s type=%s", session.session_id, type(e).__name__)
        if session.session_id not in _tts_failed:
            _tts_failed.add(session.session_id)
            notify_family(db, room.room_id, "TTS_ERROR", f"{room.elder_name} 님 기기에서 음성 재생에 문제가 있어요")
    return AiOut(
        text=reply.text,
        audio_b64=audio_b64,
        suggestions=reply.suggestions,
        choice_mode=reply.choice_mode,
        question_type=reply.question_type,
    )


def _expired(session: TalkSession) -> bool:
    return (now_kst() - session.started_at).total_seconds() > MAX_SESSION_SEC


def _stale(db, session: TalkSession) -> bool:
    last = db.scalar(select(func.max(SessionTurn.created_at)).where(SessionTurn.session_id == session.session_id))
    return bool(last) and now_kst() - last > timedelta(minutes=SESSION_RESUME_MIN)


def _locked(session_id: uuid.UUID) -> bool:
    return _low_conf[session_id] >= STT_FAIL_LOCK


def _finish(db, session: TalkSession, reason: str) -> None:
    if session.ended_at is not None:
        return
    now = now_kst()
    session.ended_at = now
    session.end_reason = reason
    session.duration_sec = int((now - session.started_at).total_seconds())
    if reason != "ERROR" and session.kind == "MEMORY" and session.pick_id:
        pick = db.get(DailyPick, session.pick_id)
        if pick and pick.completed_session_id is None:  # 완료 기록은 세션 ID 로 1회만 (FR-ME-007)
            pick.status = "COMPLETED"
            pick.completed_at = now
            pick.completed_session_id = session.session_id
    if reason == "ERROR":
        errors_today = db.scalar(
            select(func.count())
            .select_from(TalkSession)
            .where(
                TalkSession.room_id == session.room_id,
                TalkSession.end_reason == "ERROR",
                TalkSession.ended_at >= now.replace(hour=0, minute=0, second=0, microsecond=0),
            )
        )
        already = db.scalar(
            select(func.count())
            .select_from(Notification)
            .where(
                Notification.room_id == session.room_id,
                Notification.kind == "SESSION_ERROR_3X",
                Notification.sent_at >= now.replace(hour=0, minute=0, second=0, microsecond=0),
            )
        )
        if (errors_today or 0) + 1 >= SESSION_ERROR_ALERT and not already:
            room = db.get(FamilyRoom, session.room_id)
            notify_family(db, room.room_id, "SESSION_ERROR_3X", f"{room.elder_name} 님 대화가 오늘 3번 중단됐어요")
    for store in (_no_response, _low_conf, _last_reply):
        store.pop(session.session_id, None)
    _tts_failed.discard(session.session_id)


def _out(db, session, room, reply, state="CONTINUE", end_reason=None) -> SessionOut:
    return SessionOut(
        session_id=session.session_id,
        ai=_ai_out(db, session, room, reply),
        state=state,
        end_reason=end_reason,
        turn_no=session.turn_count,
        input_locked=_locked(session.session_id),
    )


@router.post("", response_model=SessionOut, status_code=201)
def create_session(body: SessionCreateIn, device: CurrentDevice, db: DB):
    room = db.get(FamilyRoom, device.room_id)
    existing = db.get(TalkSession, body.session_id)
    if existing:  # 같은 session_id 재요청은 멱등
        if existing.room_id != room.room_id:
            raise ApiError(404, "SESSION_NOT_FOUND", "대화를 찾을 수 없어요")
        reply = _last_reply.get(existing.session_id) or coach.FALLBACK_QUESTION
        state = "ENDED" if existing.ended_at else "CONTINUE"
        return _out(db, existing, room, reply, state, existing.end_reason)
    pick = None
    if body.pick_id:
        pick = db.get(DailyPick, body.pick_id)
        if not pick or pick.room_id != room.room_id:
            raise ApiError(404, "PICK_NOT_FOUND", "오늘의 한 장을 찾을 수 없어요")
    photo_id = body.photo_id or (pick.photo_id if pick else None)
    if photo_id:
        photo = db.get(Photo, photo_id)
        if not photo or photo.room_id != room.room_id:
            raise ApiError(404, "PHOTO_NOT_FOUND", "사진을 찾을 수 없어요")
    session = TalkSession(
        session_id=body.session_id,
        room_id=room.room_id,
        kind=body.kind,
        pick_id=body.pick_id,
        photo_id=photo_id,
        input_mode=device.input_mode,
        turn_count=1,
    )
    db.add(session)
    db.flush()
    reply = _ask(db, session, _ctx(db, room, session), closing=False)
    db.commit()
    return _out(db, session, room, reply)


@router.get("/{session_id}", response_model=SessionGetOut)
def get_session(session_id: uuid.UUID, device: CurrentDevice, db: DB):
    session = _get(db, session_id, device)
    ended = session.ended_at is not None or _expired(session) or _stale(db, session)
    reply = _last_reply.get(session.session_id)
    if reply is None:
        last = _last_ai_turn(db, session.session_id)
        reply = CoachReply(text=last.text, suggestions=[], question_type=last.question_type or "NONE") if last else None
    return SessionGetOut(
        session_id=session.session_id,
        state="ENDED" if ended else "CONTINUE",
        end_reason=session.end_reason,
        last_ai=AiOut(
            text=reply.text,
            suggestions=reply.suggestions,
            choice_mode=reply.choice_mode,
            question_type=reply.question_type,
        )
        if reply
        else None,
        turn_no=session.turn_count,
        input_locked=_locked(session.session_id),
    )


@router.post("/{session_id}/turns", response_model=SessionOut)
def post_turn(session_id: uuid.UUID, body: TurnIn, device: CurrentDevice, db: DB):
    session = _get(db, session_id, device)
    room = db.get(FamilyRoom, session.room_id)
    if session.ended_at is not None:
        raise ApiError(409, "SESSION_ENDED", "이미 끝난 대화예요")

    if _expired(session):  # 5분 상한 (D8)
        reply = _ask(db, session, _ctx(db, room, session), closing=True)
        _finish(db, session, "LIMIT")
        db.commit()
        return _out(db, session, room, reply, "ENDED", "LIMIT")

    if body.event == "NO_RESPONSE":  # 무응답 3단계: 재질문 → 칩만 → 종료
        _no_response[session.session_id] += 1
        stage = _no_response[session.session_id]
        if stage >= NO_RESPONSE_END:
            reply = _ask(db, session, _ctx(db, room, session), closing=True)
            _finish(db, session, "NO_RESPONSE")
            db.commit()
            return _out(db, session, room, reply, "ENDED", "NO_RESPONSE")
        last = _last_reply.get(session.session_id) or coach.FALLBACK_QUESTION
        if stage >= 2:
            last = last.model_copy(
                update={"choice_mode": "TWO_BUTTONS", "suggestions": (last.suggestions or ["네", "아니요"])[:2]}
            )
        return _out(db, session, room, last)

    text = (body.text or "").strip()
    if not text:
        raise ApiError(422, "TEXT_REQUIRED", "말씀 내용이 비어 있어요")
    if body.input_type == "VOICE" and _locked(session.session_id):
        raise ApiError(409, "INPUT_LOCKED", "지금은 버튼으로만 답할 수 있어요")
    if (
        body.input_type == "VOICE"
        and not body.retried
        and body.stt_confidence is not None
        and body.stt_confidence < STT_CONF_MIN
    ):  # 저신뢰: 저장하지 않고 확인 질문만 (D5). "맞아요" 면 같은 문장을 retried=true 로 다시 보낸다.
        _low_conf[session.session_id] += 1
        return _out(db, session, room, coach.confirm_question(text))

    _no_response[session.session_id] = 0
    last_ai = _last_ai_turn(db, session.session_id)
    _add_turn(
        db,
        session,
        "ELDER",
        text,
        stt_confidence=body.stt_confidence,
        input_type=body.input_type,
        retried=body.retried,
        reply_to_turn_id=last_ai.turn_id if last_ai else None,
    )
    ctx = _ctx(db, room, session)
    if session.turn_count >= MAX_TURNS:  # 8번째 답 → 마무리 인사 후 종료
        reply = _ask(db, session, ctx, closing=True)
        _finish(db, session, "COMPLETED")
        db.commit()
        return _out(db, session, room, reply, "ENDED", "COMPLETED")
    session.turn_count += 1
    reply = _ask(db, session, ctx, closing=False)
    db.commit()
    return _out(db, session, room, reply)


@router.post("/{session_id}/end", response_model=SessionEndOut)
def end_session(session_id: uuid.UUID, body: SessionEndIn, device: CurrentDevice, db: DB):
    session = _get(db, session_id, device)
    if session.ended_at is None:
        _finish(db, session, body.reason)
        db.commit()
    return SessionEndOut(
        session_id=session.session_id, state="ENDED", end_reason=session.end_reason, turn_no=session.turn_count
    )
