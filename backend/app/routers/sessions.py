"""회상·일기 대화 세션 — 음성 왕복 걷는 해골 (초석 원안 D). 계약은 schemas/sessions.py.

턴 정의: AI 질문 1 + 어르신 답 1 = 1턴. sessions.turn_count = 지금까지 낸 AI 질문 수
(만들 때 1, 최대 MAX_TURNS=6, D52 ⑦).
마지막(6번째) 답을 받으면 AI 가 마무리 인사(CLOSING) 를 하고 state=ENDED, end_reason=COMPLETED.
kind=DIARY(일기 대화)는 질문 3개(DIARY_TURNS)로 끝난다. 초안·그림일기·게시는 routers/diaries.py (D36).
kind=ALBUM(사진첩)은 질문 2개(ALBUM_TURNS)로 끝난다 (FR-ME-008).
턴은 sessions.turns JSON 배열에 한 칸씩 (D38). turn_no 는 순번 (1=AI, 2=ELDER, 3=AI …).
서버가 지키는 상한: 6턴, 5분(대화한 시간 — 보류는 빼고 잼), 무응답 3단계, 저신뢰 2회 → input_locked (D5, D8).
마지막 턴 뒤 30분이 지나면 끝난 대화로 본다 (보류 30분 복귀 — 뒤로 키로 나갔다 '이어서', D52 ⑥).
저신뢰 음성은 저장하지 않고 확인 질문을 하며 그 문장을 메모리에 맡겨 둔다.
다음 답이 '맞아요'(말·칩)면 맡긴 문장을 답으로 저장하고, '다시 말할게요·아니요'면 원래 질문을 다시,
다른 말이면 그 말이 새 답이다 ('맞아요'가 답으로 저장되던 D33 의 문제, D52 ③).
"""

from __future__ import annotations

import base64
import logging
import time
import uuid
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any

from fastapi import APIRouter
from sqlalchemy import func, select

from app.ai import coach, quiz, tts
from app.ai.schemas import CoachReply
from app.config import (
    ALBUM_PER_DAY,
    ALBUM_TURNS,
    DIARY_TURNS,
    MAX_SESSION_SEC,
    MAX_TURNS,
    NO_RESPONSE_END,
    PAUSE_GAP_SEC,
    QUIZ_TURN,
    SESSION_ERROR_ALERT,
    SESSION_RESUME_MIN,
    STT_CONF_MIN,
    STT_FAIL_LOCK,
    now_kst,
    today_kst,
)
from app.deps import DB, CurrentDevice
from app.errors import ApiError
from app.models import DailyPick, FamilyRoom, Notification, Photo, TalkSession
from app.routers.devices import notify_family
from app.schemas.sessions import (
    AiOut,
    SessionCreateIn,
    SessionEndIn,
    SessionEndOut,
    SessionGetOut,
    SessionOut,
    TurnIn,
    TurnOut,
)

log = logging.getLogger("app.sessions")
router = APIRouter(prefix="/elder/sessions", tags=["sessions"])

# 일기로 남기는 종료 사유. 그만할래요(USER_STOP)·무응답·오류로 끝난 일기 대화는 저장하지 않는다 (FR-DI-003)
DIARY_SAVED = ("COMPLETED", "LIMIT")

# ponytail: 세션별 카운터는 프로세스 메모리 (uvicorn --workers 1 전제, D9). 재시작하면 사라지지만
# 세션은 어차피 30분 지나면 ENDED 취급이라 무방. 수평 확장이 필요해지면 sessions 테이블 컬럼으로.
_no_response: dict[uuid.UUID, int] = defaultdict(int)
_low_conf: dict[uuid.UUID, int] = defaultdict(int)
_last_reply: dict[uuid.UUID, CoachReply] = {}
_tts_failed: set[uuid.UUID] = set()
# 확인을 기다리는 저신뢰 문장 (문장, 신뢰도). 재시작으로 잃으면 그 뒤 '맞아요'는 보통 답으로 저장된다(드묾)
_pending: dict[uuid.UUID, tuple[str, float | None]] = {}


def load_session(db, session_id: uuid.UUID, device, lock: bool = False) -> TalkSession:
    """이 기기 가족방의 세션만 돌려준다 (다른 방 것은 없는 것처럼 404). routers/diaries.py 도 쓴다.

    lock=True 면 세션 행을 잠근다(FOR UPDATE, 커밋까지). 같은 대화에 턴이 동시에 와도 turns 를 덮어쓰지 않게 (D38).
    """
    session = db.get(TalkSession, session_id, with_for_update=lock)
    if not session or session.room_id != device.room_id:
        raise ApiError(404, "SESSION_NOT_FOUND", "대화를 찾을 수 없어요")
    return session


def coach_context(db, room: FamilyRoom, session: TalkSession) -> coach.CoachContext:
    """코치에 넘길 데이터 (호칭·사진 설명·지금까지의 턴). routers/diaries.py 도 쓴다."""
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
        # 문제였던 AI 턴에는 quiz 표시 → 다음 턴에 평가 없이 "아, 그렇군요"로 받게 (FR-AI-003). 일기 턴엔 없음
        turns=[
            {"speaker": t["speaker"], "text": t["text"]} | ({"quiz": True} if t.get("question_code") else {})
            for t in session.turns
        ],
    )


def _add_turn(session: TalkSession, speaker: str, text: str, **fields: Any) -> dict[str, Any]:
    """turns 에 한 칸 추가. 값이 None 인 키는 넣지 않는다 (키 목록: schema.sql sessions 주석)."""
    turn = {"turn_no": len(session.turns) + 1, "speaker": speaker, "text": text, "created_at": now_kst().isoformat()}
    turn |= {k: v for k, v in fields.items() if v is not None}
    session.turns = [*session.turns, turn]  # 새 리스트를 넣어야 SQLAlchemy 가 바뀐 것을 안다
    return turn


def _last_ai_turn(session: TalkSession) -> dict[str, Any] | None:
    return next((t for t in reversed(session.turns) if t["speaker"] == "AI"), None)


def _turn_times(session: TalkSession) -> list[datetime]:
    return [datetime.fromisoformat(t["created_at"]) for t in session.turns]


def _max_turns(session: TalkSession) -> int:
    if session.kind == "DIARY":
        return DIARY_TURNS
    if session.kind == "ALBUM":
        return ALBUM_TURNS
    return MAX_TURNS


def _fallback(session: TalkSession) -> CoachReply:
    """마지막 질문을 메모리에서 잃었을 때(서버 재시작) 다시 보여 줄 질문."""
    return coach.diary_fallback(session.turn_count) if session.kind == "DIARY" else coach.FALLBACK_QUESTION


def _ask(
    db, session: TalkSession, ctx: coach.CoachContext, end: str | None = None, turn_no: int | None = None
) -> tuple[CoachReply, str]:
    """코치 호출 + AI 턴 저장 (latency_ms 기록). end(종료 사유)가 있으면 질문 대신 마무리 인사.

    turn_no = 이번이 몇 번째 AI 질문인지 (기본 session.turn_count). 회상(MEMORY) 4번째 질문은 문제 은행 문제이고
    출제 기록은 그 AI 턴의 question_code (QUIZ_TURN, D42). 사진첩(ALBUM)·일기는 문제 없음 (FR-ME-008).
    돌려주는 signal 이 SAD·STOP 이면 reply 는 마무리 인사 — 질문 중이었다면 호출자가 대화를 끝낸다 (FR-AI-005).
    """
    t0 = time.perf_counter()
    turn_no = turn_no or session.turn_count
    signal, code = "NONE", None
    if session.kind == "DIARY":
        if end is None:
            reply = coach.diary_question(ctx, turn_no)
        else:  # "일기를 써 볼게요"는 일기를 쓸 때만. 무응답으로 끝나면 저장하지 않으니 다른 인사
            reply = coach.DIARY_CLOSING if end in DIARY_SAVED else coach.DIARY_STOP
    elif end:
        reply, signal = coach.closing(ctx, turn_no, _max_turns(session))
    else:
        picked = quiz.pick(db, session) if session.kind == "MEMORY" and turn_no == QUIZ_TURN else None
        # 최대 질문 수도 같이 넘긴다 — 사진첩은 2, 오늘의 한 장은 6 (AI 가 몇 번째 질문인지 알고 말하게)
        reply, signal = coach.next_question(ctx, turn_no, picked, _max_turns(session))
        code = picked.code if picked and signal == "NONE" else None
    if signal == "SAD":
        session.emotion_flag = "SAD"  # 가족 대시보드·주간 요약용 (FR-AI-005, FR-FD-006)
    _add_turn(
        session,
        "AI",
        reply.text,
        question_type=reply.question_type,
        question_code=code,
        latency_ms=int((time.perf_counter() - t0) * 1000),
    )
    _last_reply[session.session_id] = reply
    return reply, signal


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
            db.commit()  # _out 은 각 핸들러의 commit 뒤에 불리므로 여기서 따로 커밋해야 알림이 남는다
    return AiOut(
        text=reply.text,
        audio_b64=audio_b64,
        suggestions=reply.suggestions,
        choice_mode=reply.choice_mode,
        question_type=reply.question_type,
    )


def _talk_seconds(session: TalkSession) -> float:
    """5분 상한용 '대화한 시간'. 시작·각 턴·지금 사이 간격을 PAUSE_GAP_SEC 까지만 더한다.

    더 긴 간격은 보류(전화·홈 버튼)로 보고 빼야 '30분 안 복귀'가 가능하다. 턴 시각이 turns 에 있어 칸 추가가 필요 없다.
    """
    times = [session.started_at, *_turn_times(session), now_kst()]
    return sum(min((b - a).total_seconds(), PAUSE_GAP_SEC) for a, b in zip(times, times[1:]))


def _expired(session: TalkSession) -> bool:
    return _talk_seconds(session) > MAX_SESSION_SEC


def _stale(session: TalkSession) -> bool:
    times = _turn_times(session)
    return bool(times) and now_kst() - times[-1] > timedelta(minutes=SESSION_RESUME_MIN)


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
        db.flush()  # 지금 끝나는 이 세션도 세도록 먼저 반영 (그래서 아래 비교에 +1 이 없다)
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
        if (errors_today or 0) >= SESSION_ERROR_ALERT and not already:
            room = db.get(FamilyRoom, session.room_id)
            notify_family(db, room.room_id, "SESSION_ERROR_3X", f"{room.elder_name} 님 대화가 오늘 3번 중단됐어요")
    for store in (_no_response, _low_conf, _last_reply, _pending):
        store.pop(session.session_id, None)
    # _tts_failed 는 여기서 지우지 않는다: 끝인사를 읽다가 또 실패하면 가족 알림이 한 번 더 간다 (D5 는 대화에 1건)


def _photo_url(db, session: TalkSession) -> str | None:
    photo = db.get(Photo, session.photo_id) if session.photo_id else None
    return f"/api/media/{photo.object_key}" if photo else None


def _out(db, session, room, reply, state="CONTINUE", end_reason=None) -> SessionOut:
    return SessionOut(
        session_id=session.session_id,
        kind=session.kind,
        photo_url=_photo_url(db, session),
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
        reply = _last_reply.get(existing.session_id) or _fallback(existing)
        state = "ENDED" if existing.ended_at else "CONTINUE"
        return _out(db, existing, room, reply, state, existing.end_reason)
    if body.kind == "ALBUM":
        albums_today = db.scalar(
            select(func.count())
            .select_from(TalkSession)
            .where(
                TalkSession.room_id == room.room_id,
                TalkSession.kind == "ALBUM",
                TalkSession.started_at >= now_kst().replace(hour=0, minute=0, second=0, microsecond=0),
            )
        )
        if (albums_today or 0) >= ALBUM_PER_DAY:
            raise ApiError(409, "ALBUM_LIMIT", "오늘은 사진첩 이야기를 다 했어요. 내일 또 해요")
    pick = None
    if body.pick_id:
        pick = db.get(DailyPick, body.pick_id)
        if not pick or pick.room_id != room.room_id:
            raise ApiError(404, "PICK_NOT_FOUND", "오늘의 한 장을 찾을 수 없어요")
        # 옛 화면에서 누른 경우를 막는다 (D45 ④): 홈을 켜 둔 채 날이 바뀌었거나, 건너뛴 사진을 다른 창에서 누름.
        # 안 막으면 어제 사진으로 대화가 열리고, 끝날 때 어제 pick 이 COMPLETED 가 된다.
        # 화면(ELDER_HOME_001)은 이 두 코드를 받으면 홈을 다시 읽는다
        if pick.pick_date != today_kst():
            raise ApiError(409, "PICK_EXPIRED", "날짜가 바뀌었어요. 오늘 사진을 다시 보여 드릴게요")
        if pick.status == "SKIPPED":
            raise ApiError(409, "PICK_SKIPPED", "오늘 사진은 건너뛰었어요")
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
        input_mode=room.device_input_mode,
        turn_count=1,
        turns=[],
    )
    db.add(session)
    db.flush()
    reply, _ = _ask(db, session, coach_context(db, room, session))  # 어르신 말 전이라 signal 은 늘 NONE (coach)
    db.commit()
    return _out(db, session, room, reply)


@router.get("/{session_id}", response_model=SessionGetOut)
def get_session(session_id: uuid.UUID, device: CurrentDevice, db: DB):
    session = load_session(db, session_id, device)
    ended = session.ended_at is not None or _expired(session) or _stale(session)
    reply = _last_reply.get(session.session_id)
    if reply is None and not ended and session.kind == "DIARY":
        reply = _fallback(session)  # 재시작으로 칩을 잃음 → NO_RESPONSE 와 같은 고정 질문·칩 (기분 질문은 칩 4개)
    if reply is None:
        last = _last_ai_turn(session)
        reply = (
            CoachReply(text=last["text"], suggestions=[], question_type=last.get("question_type") or "NONE")
            if last
            else None
        )
    return SessionGetOut(
        session_id=session.session_id,
        kind=session.kind,
        photo_url=_photo_url(db, session),
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
        turns=[TurnOut(speaker=t["speaker"], text=t["text"]) for t in session.turns],  # 이어서 할 때 지난 말풍선
    )


def _unconfirmed(body: TurnIn) -> bool:
    """저신뢰 음성인데 어르신이 아직 '맞아요' 하지 않은 답 — 저장하지 않는다 (D5)."""
    return (
        body.input_type == "VOICE"
        and not body.retried
        and body.stt_confidence is not None
        and body.stt_confidence < STT_CONF_MIN
    )


def _confirmed(session: TalkSession, body: TurnIn, text: str) -> tuple[TurnIn, str, bool]:
    """바로 앞이 확인 질문이었으면 답을 푼다 → (저장할 body, 저장할 말, '아니요'였는지). 맡긴 문장은 비운다 (D52 ③).

    '맞아요·네'(말·칩) = 맡긴 문장이 답(확인을 거친 음성, retried=true). '다시 말할게요·아니요' = 저장하지 않음.
    다른 말 = 그 말이 새 답.
    """
    pending = _pending.pop(session.session_id, None)
    answer = coach.confirm_answer(text) if pending else None
    if answer == "YES":
        update = {"input_type": "VOICE", "stt_confidence": pending[1], "retried": True}
        return body.model_copy(update=update), pending[0], False
    return body, text, answer == "NO"


def _save_elder(db, session: TalkSession, body: TurnIn, text: str) -> None:
    last_ai = _last_ai_turn(session)
    _add_turn(
        session,
        "ELDER",
        text,
        stt_confidence=body.stt_confidence,
        input_type=body.input_type,
        retried=body.retried,
        reply_to_turn_no=last_ai["turn_no"] if last_ai else None,
    )


@router.post("/{session_id}/turns", response_model=SessionOut)
def post_turn(session_id: uuid.UUID, body: TurnIn, device: CurrentDevice, db: DB):
    session = load_session(db, session_id, device, lock=True)
    room = db.get(FamilyRoom, session.room_id)
    if session.ended_at is not None:
        raise ApiError(409, "SESSION_ENDED", "이미 끝난 대화예요")
    if _stale(session):  # 마지막 턴 뒤 30분 → 끝난 대화 (GET 과 같은 규칙)
        _finish(db, session, "NO_RESPONSE")
        db.commit()
        raise ApiError(409, "SESSION_ENDED", "이미 끝난 대화예요")

    if _expired(session):  # 5분 상한 (D8). 방금 한 답은 저장한 뒤 마무리
        text = (body.text or "").strip()
        if text and body.event is None and not _unconfirmed(body):
            body, text, said_no = _confirmed(session, body, text)  # 확인 질문 뒤 '맞아요'면 맡긴 문장을
            if not said_no:
                _save_elder(db, session, body, text)
        reply, _ = _ask(db, session, coach_context(db, room, session), end="LIMIT")
        _finish(db, session, "LIMIT")
        db.commit()
        return _out(db, session, room, reply, "ENDED", "LIMIT")

    if body.event == "NO_RESPONSE":  # 무응답 3단계: 재질문 → 칩만 → 종료
        _pending.pop(session.session_id, None)  # 확인 질문에 답이 없으면 맡긴 문장은 버리고 원래 질문을 다시
        _no_response[session.session_id] += 1
        stage = _no_response[session.session_id]
        if stage >= NO_RESPONSE_END:
            reply, _ = _ask(db, session, coach_context(db, room, session), end="NO_RESPONSE")
            _finish(db, session, "NO_RESPONSE")
            db.commit()
            return _out(db, session, room, reply, "ENDED", "NO_RESPONSE")
        last = _last_reply.get(session.session_id) or _fallback(session)
        mood_question = session.kind == "DIARY" and session.turn_count >= DIARY_TURNS
        if stage >= 2 and not mood_question:  # 일기 기분 질문은 칩 4개 그대로 (둘만 남기면 기분이 한쪽으로 치우친다)
            last = last.model_copy(
                update={"choice_mode": "TWO_BUTTONS", "suggestions": (last.suggestions or ["네", "아니요"])[:2]}
            )
        db.commit()  # 저장할 것은 없다 — 세션 행 잠금을 여기서 푼다. 아래 _out 이 음성을 만드는 몇 초 동안 쥐지 않게
        return _out(db, session, room, last)

    text = (body.text or "").strip()
    if not text:
        raise ApiError(422, "TEXT_REQUIRED", "말씀 내용이 비어 있어요")
    if body.input_type == "VOICE" and _locked(session.session_id):
        raise ApiError(409, "INPUT_LOCKED", "지금은 버튼으로만 답할 수 있어요")
    if _unconfirmed(body):  # 저신뢰: 저장하지 않고 문장을 맡겨 둔 채 확인 질문만 (D5, D52 ③)
        _low_conf[session.session_id] += 1
        _pending[session.session_id] = (text, body.stt_confidence)
        db.commit()  # 위 재질문과 같은 이유 — 음성을 만들기 전에 세션 행 잠금을 푼다
        return _out(db, session, room, coach.confirm_question(text))
    body, text, said_no = _confirmed(session, body, text)
    if said_no:  # 잘못 들었다 → 저장 없이 원래 질문을 다시 (화면은 [다시 말할게요]를 보통 바로 녹음으로 받는다)
        db.commit()
        return _out(db, session, room, _last_reply.get(session.session_id) or _fallback(session))

    _no_response[session.session_id] = 0
    _save_elder(db, session, body, text)
    ctx = coach_context(db, room, session)
    if session.turn_count >= _max_turns(session):  # 마지막 답(회상 6번째·일기 3번째) → 마무리 인사 후 종료
        reply, _ = _ask(db, session, ctx, end="COMPLETED")
        _finish(db, session, "COMPLETED")
        db.commit()
        return _out(db, session, room, reply, "ENDED", "COMPLETED")
    reply, signal = _ask(db, session, ctx, turn_no=session.turn_count + 1)
    if signal != "NONE":  # 슬픔·그만 (FR-AI-005): 문제 없이 마무리 인사로 바로 끝낸다. turn_count(질문 수)는 그대로
        reason = "USER_STOP" if signal == "STOP" else "COMPLETED"
        _finish(db, session, reason)
        db.commit()
        return _out(db, session, room, reply, "ENDED", reason)
    session.turn_count += 1
    db.commit()
    return _out(db, session, room, reply)


@router.post("/{session_id}/end", response_model=SessionEndOut)
def end_session(session_id: uuid.UUID, body: SessionEndIn, device: CurrentDevice, db: DB):
    session = load_session(db, session_id, device)
    if session.ended_at is None:
        _finish(db, session, body.reason)
        db.commit()
    return SessionEndOut(
        session_id=session.session_id, state="ENDED", end_reason=session.end_reason, turn_no=session.turn_count
    )
