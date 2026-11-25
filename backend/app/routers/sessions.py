"""회상·일기 대화 세션 — 음성 왕복 걷는 해골 (초석 원안 D). 계약은 schemas/sessions.py.

턴 정의: AI 질문 1 + 어르신 답 1 = 1턴. sessions.turn_count = 지금까지 낸 AI 질문 수
(만들 때 1, 최대 MAX_TURNS=5, D97 — 11/24 전 4·11/18 전 6). 그날 첫 회상 대화가 지난 대화의 이야기로 시작하면
그 질문도 5번 안에 든다(첫 AI 턴의 fact_id — 코치에 넘기는 사진 질문 번호만 하나씩 밀린다, AI-07 D77·D79).
생각 문제는 늘 끝에서 두 번째(QUIZ_TURN, 어제 이야기 질문도 세는 순번).
마지막(5번째) 답을 받으면 AI 가 마무리 인사(CLOSING) 를 하고 state=ENDED, end_reason=COMPLETED.
kind=DIARY(일기 대화)는 질문 5개(DIARY_TURNS)로 끝난다. 초안·그림일기·게시는 routers/diaries.py (D36).
kind=ALBUM(사진첩)은 질문 2개(ALBUM_TURNS)로 끝난다 (FR-ME-008).
턴은 sessions.turns JSON 배열에 한 칸씩 (D38). turn_no 는 순번 (1=AI, 2=ELDER, 3=AI …).
서버가 지키는 상한: 5턴(회상), 5분(대화한 시간 — 보류는 빼고 잼), 무응답 3단계, 저신뢰 2회 → input_locked (D5, D8).
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
from typing import Any, Literal

from fastapi import APIRouter
from sqlalchemy import func, select

from app.ai import classify, coach, quiz, story, tts
from app.ai.schemas import CoachReply, has_body_words, has_risk_words
from app.config import (
    ALBUM_PER_DAY,
    ALBUM_TURNS,
    CHAT_SESSION_SEC,
    CHAT_TURNS,
    CLASSIFY_SYNC_SEC,
    COMFORT_TURNS,
    DIARY_TURNS,
    MAX_SESSION_SEC,
    MAX_TURNS,
    MOOD_LOW_DAYS,
    MOOD_LOW_WINDOW_DAYS,
    MORE_SESSION_SEC,
    MORE_TURNS,
    NO_RESPONSE_END,
    OLD_PHOTO_CONF_MIN,
    PAUSE_GAP_SEC,
    QUIZ_TURN,
    SESSION_ERROR_ALERT,
    SESSION_RESUME_MIN,
    STT_CONF_MIN,
    STT_FAIL_LOCK,
    TZ,
    now_kst,
    today_kst,
)
from app.deps import DB, CurrentDevice
from app.errors import ApiError
from app.models import DailyPick, FamilyRoom, Notification, Photo, TalkSession
from app.routers.devices import notify_family
from app.routers.mood import LOW_DAYS_TITLE
from app.schemas.sessions import (
    AiOut,
    ChatItemOut,
    SessionCreateIn,
    SessionEndIn,
    SessionEndOut,
    SessionGetOut,
    SessionOut,
    TurnIn,
    TurnOut,
)
from app.services import alerts, care, chat

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
# '더 얘기할래'로 더 준 질문 수 (11/25). ponytail: 메모리라 서버를 다시 켜면 원래 수로 끝난다(D9 워커 1개 전제)
_more: dict[uuid.UUID, int] = {}


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
                "taken_year": photo.taken_year,  # 찍은 날을 모를 때 가족이 고른 연도 — '그 해쯤' (11/23)
                # 가족이 '올린 사진'에서 고른 활동 (D73). 'none'(맞는 것 없음)은 넘기지 않는다
                "activity": photo.corrected_activity if photo.corrected_activity not in (None, "none") else None,
                # 지난 대화에서 어르신이 이 사진을 바로잡아 주신 내용 (FR-ME-009) — 가족 설명·AI 짐작보다 먼저 따른다
                "elder_note": photo.elder_note,
            }
            if photo
            else None
        ),
        # 문제였던 AI 턴에는 quiz 표시 → 다음 턴에 평가 없이 "아, 그렇군요"로 받게 (FR-AI-003). 일기 턴엔 없음.
        # 어제 이야기 턴에는 story 표시 → 다음 턴에 날짜를 다시 말하지 않고, '그런 말 안 했어'면 DENY (D77)
        turns=[
            {"speaker": t["speaker"], "text": t["text"]}
            | ({"quiz": True} if t.get("question_code") else {})
            | ({"story": True} if t.get("fact_id") or t.get("care") else {})
            for t in session.turns
        ],
        # 일기 사진이 옛 사진이면 1·2번을 그 사진 속 그때로 (FR-DI-002, D58). 분류(AI-04 #29) 전에는 늘 False.
        # NUMERIC 칸은 Decimal — Decimal('0.80') >= 0.8 은 거짓이라 float 로 비교한다 (quiz.py 와 같이)
        old_photo=bool(
            session.kind == "DIARY"
            and photo
            and photo.analyzed_at is not None
            and photo.is_old
            and photo.confidence is not None
            and float(photo.confidence) >= OLD_PHOTO_CONF_MIN
        ),
        # 분류 AI 가 본 '보이는 모습' 한 줄 (D71) — 대화에 못 쓰는 사진(usable=false)이면 넘기지 않는다.
        # 어르신이 바로잡아 주신 사진도 넘기지 않는다 — 틀렸다고 하신 짐작을 다시 꺼내지 않게 (FR-ME-009)
        scene=photo.ai_scene if photo and photo.usable is not False and not photo.elder_note else None,
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


def _story_offset(session: TalkSession) -> int:
    """첫 AI 질문이 지난 대화의 이야기(fact_id)면 1 — 코치에 넘기는 사진 질문 번호가 하나씩 밀린다 (D77).

    최대 질문 수·문제 차례는 밀리지 않는다 — 어제 이야기 질문도 MAX_TURNS 5번 안에 든다 (D79·D97)."""
    first = session.turns[0] if session.turns else {}
    return 1 if first.get("fact_id") or first.get("care") else 0  # 오늘의 안부(돌봄 루프)도 같은 자리


def _max_turns(session: TalkSession) -> int:
    more = _more.get(session.session_id, 0)
    if session.kind == "CHAT":
        return CHAT_TURNS + more
    if session.kind == "DIARY":
        return DIARY_TURNS + more
    if session.kind == "ALBUM":
        return ALBUM_TURNS + more
    return MAX_TURNS + more


def _grant_more(session: TalkSession, text: str) -> None:
    """마지막 답(일기는 기분 묻기 앞 답부터)에 '더 얘기할래'가 있으면 한 번만 질문·시간을 더 준다 (11/25 실사용)."""
    last = _max_turns(session) - (1 if session.kind == "DIARY" else 0)
    if session.session_id not in _more and session.turn_count >= last and coach.wants_more(text):
        _more[session.session_id] = MORE_TURNS


def _fallback(session: TalkSession) -> CoachReply:
    """마지막 질문을 메모리에서 잃었을 때(서버 재시작) 다시 보여 줄 질문."""
    if session.kind == "DIARY":
        return coach.diary_fallback(session.turn_count, _max_turns(session))
    if session.kind == "CHAT":
        return coach.CHAT_FALLBACK
    return coach.FALLBACK_QUESTION


def _ask(
    db,
    session: TalkSession,
    ctx: coach.CoachContext,
    end: str | None = None,
    turn_no: int | None = None,
    resume_of: uuid.UUID | None = None,
) -> tuple[CoachReply, str]:
    """코치 호출 + AI 턴 저장 (latency_ms 기록). end(종료 사유)가 있으면 질문 대신 마무리 인사.

    turn_no = 이번이 몇 번째 AI 질문인지 (기본 session.turn_count). 회상(MEMORY) 끝에서 두 번째 질문은 생각 문제이고
    출제 기록은 그 AI 턴의 question_code (QUIZ_TURN, D42). 사진첩(ALBUM)·일기는 문제 없음 (FR-ME-008).
    돌려주는 signal 이 SAD·STOP·BODY 이면 reply 는 마무리 인사 — 질문 중이었다면 호출자가 대화를 끝낸다 (FR-AI-005).
    RISK 면 AI 턴을 남기지 않고 돌려준다 — 호출자가 _comfort 로 위로를 잇는다 (11/23).
    LOW·SAD·RISK·private 은 _note_mood 가 대화 기록과 가족 알림으로 남긴다 (D55).
    잡담(CHAT, D106)은 chat_buddy 가 말하고, 표정·가자는 화면·제목을 AI 턴에 함께 남긴다. resume_of 는 잡담 첫 말에만.
    """
    t0 = time.perf_counter()
    turn_no = turn_no or session.turn_count
    off = _story_offset(session)  # 코치에는 사진 질문 번호로 넘긴다 — 어제 이야기 질문은 세지 않는다 (D77)
    signal, private, code = "NONE", False, None
    if session.kind == "CHAT":
        room = db.get(FamilyRoom, session.room_id)
        data = chat.data(db, room, session, closing=end is not None, max_turns=_max_turns(session), resume_of=resume_of)
        reply, signal, private = coach.chat_reply(data)
    elif session.kind == "DIARY":
        if end is None:
            reply = coach.diary_question(ctx, turn_no, _max_turns(session))
            # 일기 동무 AI 가 직전 답에서 본 신호 (11/19 S3) — 2~4번째 질문을 만들 때만 온다(1번은 어르신 말 전,
            # 5번 기분 질문과 고정 문장에는 없다). 위급이면 회상 대화와 같은 코드 문장으로 마무리
            if any(t["speaker"] == "ELDER" for t in ctx.turns):
                signal = getattr(reply, "signal", "NONE")
            reply = coach.URGENT_CLOSINGS.get(signal, reply)
        else:  # "일기를 써 볼게요"는 일기를 쓸 때만. 무응답으로 끝나면 저장하지 않으니 다른 인사
            reply = coach.diary_closing(ctx) if end in DIARY_SAVED else coach.DIARY_STOP
    elif end:
        reply, signal, private = coach.closing(ctx, turn_no - off, _max_turns(session) - off)
    else:
        # 문제 차례는 어제 이야기 질문도 세는 순번 — 늘 끝에서 두 번째라 마지막은 사진 이야기로 끝난다 (D79)
        picked = quiz.pick(db, session) if session.kind == "MEMORY" and turn_no == QUIZ_TURN else None
        # 최대 질문 수도 넘긴다(AI 가 몇 번째인지 알고 말하게) — 사진첩 2, 오늘의 한 장 5(어제 이야기가 있으면 4)
        reply, signal, private = coach.next_question(ctx, turn_no - off, picked, _max_turns(session) - off)
        # 출제 기록: 은행 원문이면 그 code, AI 가 쓴 생각 문제면 GEN-유형 (D72). 마무리로 바뀐 턴은 기록 없음
        code = quiz.record_code(picked, reply.text) if picked and signal not in coach.ENDING_SIGNALS else None
    # AI 가 실패한 턴은 어르신 말을 읽지 못한 것(coach.UNREAD) — 아래부터는 신호 없음(NONE)으로 이어 간다
    read = signal != coach.UNREAD
    if not read:
        signal = "NONE"
    last = _last_ai_turn(session)
    # 오늘의 안부에 하신 답이면 AI 가 본 신호를 돌봄 일지에 반응으로 적는다 (11/19 돌봄 루프).
    # 읽지 못한 답은 적지 않는다 — '괜찮다고 하셨어요'로 남아 가족이 잘못 안심하지 않게
    if read and last and last.get("care") and session.turns[-1].get("reply_to_turn_no") == last["turn_no"]:
        care.react(db, session.room_id, signal)
    if signal == "DENY":  # '그런 말 안 했어' — 바로 앞 질문이 어제 이야기일 때만 그 기억을 끈다 (FR-AI-008, D77)
        if last and last.get("fact_id"):
            story.deny(db, session.room_id, last["fact_id"])
        signal = "NONE"
    _note_mood(db, session, signal, private)  # 가족 마음 카드·알림·주간 요약용 (FR-AI-005, FR-FD-006, D55)
    if (
        signal == "RISK"
    ):  # 힘든 말씀 — 마무리 문장을 남기지 않는다. 호출자가 _comfort 로 위로를 잇는다 (D94 바꿈, 11/23)
        return reply, signal
    if signal == "BODY":  # 몸이 위급하다는 말 — 가족 모두에게 바로, 비밀 부탁 대화여도 보낸다 (11/19 응급)
        alerts.raise_alert(db, db.get(FamilyRoom, session.room_id), session.session_id, "BODY")
        log.info("body urgent room=%s session=%s", session.room_id, session.session_id)
    _add_turn(
        session,
        "AI",
        reply.text,
        question_type=reply.question_type,
        question_code=code,
        latency_ms=int((time.perf_counter() - t0) * 1000),
        urgent="BODY" if signal == "BODY" else None,
        # LOW 는 다음 날 안부 주제를(services/care.py), SAD 는 그 사진을 한동안 쉬게 하는 데 쓴다(services/picks.py)
        signal=signal if signal in ("LOW", "SAD") else None,
        # 잡담(D106): 표정·가자는 화면·지난 이야기 제목·이어서 한 잡담 — 회상·일기 답에는 없는 값이라 None(키 없음)
        face=getattr(reply, "face", None),
        go=getattr(reply, "go", None),
        topic=getattr(reply, "topic", None),
        resume_of=str(resume_of) if resume_of else None,
    )
    _last_reply[session.session_id] = reply
    return reply, signal


def _ask_story(db, session: TalkSession, ctx: coach.CoachContext) -> CoachReply | None:
    """그날 첫 회상 대화의 첫 질문을 지난 대화의 이야기로 (FR-AI-008, D77). 물을 기억이 없으면 None(평소 첫 질문).

    물은 기억에는 used_at 을 남긴다 — 그 기억은 다시 묻지 않고, 그 가족방은 오늘 더 묻지 않는다 (story.pick).
    AI 가 실패하면 그 기억은 묻지 않은 채 두고 고정 사진 질문으로 시작한다 — AI 를 한 번 더 기다리면
    화면이 첫 말을 기다리는 15초를 넘을 수 있다 (시간 초과 한 번이 약 9초).
    """
    t0 = time.perf_counter()
    plan = care.pick(db, session.room_id)  # 오늘의 안부가 먼저 (11/19 돌봄 루프) — 없으면 지난 이야기
    fact = story.pick(db, session.room_id) if plan is None else None
    if plan is not None:
        reply = coach.story_question(ctx, care.fact(plan), story.when(plan.heard_on), plan.heard_on)
        if reply is not None:
            plan.asked_at = now_kst()
        fields = {"care": plan.topic}
    elif fact is not None:
        reply = coach.story_question(ctx, fact.fact_text, story.when(fact.fact_date), fact.fact_date)
        if reply is not None:
            fact.used_at = now_kst()
        fields = {"fact_id": fact.fact_id}
    else:
        return None
    if reply is None:
        reply, fields = coach.FALLBACK_QUESTION, {}
    _add_turn(
        session,
        "AI",
        reply.text,
        question_type=reply.question_type,
        latency_ms=int((time.perf_counter() - t0) * 1000),
        **fields,
    )
    _last_reply[session.session_id] = reply
    return reply


_MOOD_RANK = {"NONE": 0, "SAD": 1, "LOW": 1, "RISK": 2}  # 대화의 emotion_flag 는 올라가기만 한다


def _note_mood(db, session: TalkSession, signal: str, private: bool = False) -> None:
    """AI 신호·위급 낱말을 대화 기록과 가족 알림으로 (D55). LOW·SAD → LOW, RISK → RISK.

    위급은 대화에 1번(RISK 로 올라갈 때만) 가족 모두에게 바로, 비밀 부탁 대화여도 보낸다(D55 ③).
    알림에는 대화 내용을 넣지 않는다. 로그에도 말은 남기지 않는다 (D15).
    """
    if private:
        session.private_flag = True  # '애들한테 말하지 마' — 기운 없는 날·주간 요약에서 뺀다
    flag = {"LOW": "LOW", "SAD": "LOW", "RISK": "RISK"}.get(signal)
    if flag is None or _MOOD_RANK[flag] <= _MOOD_RANK.get(session.emotion_flag, 0):
        return
    session.emotion_flag = flag
    room = db.get(FamilyRoom, session.room_id)
    if flag == "RISK":
        alerts.raise_alert(db, room, session.session_id, "MOOD")  # 가족 모두에게 알림 + 가족 홈 긴급 카드
        log.info("mood urgent room=%s session=%s", room.room_id, session.session_id)
    _check_low_days(db, room)


def _check_low_days(db, room: FamilyRoom) -> None:
    """기운 없는 말이 나온 날(한국 날짜)이 최근 7일 중 2일이면 가족에게 1건, 7일에 한 번만 (D55 ②).

    비밀 부탁 대화는 세지 않는다(D55 ③). 대화가 LOW·RISK 로 올라갈 때 부른다 — 예약 작업이 따로 필요 없다.
    ponytail: 같은 가족방의 두 대화가 같은 순간에 올라가면 2건이 갈 수 있다(워커 1개라 드묾, D9).
    """
    db.flush()  # 방금 올린 이 대화도 세도록
    first = today_kst() - timedelta(days=MOOD_LOW_WINDOW_DAYS - 1)
    since = datetime.combine(first, datetime.min.time(), tzinfo=TZ)
    started = db.scalars(
        select(TalkSession.started_at).where(
            TalkSession.room_id == room.room_id,
            TalkSession.started_at >= since,
            TalkSession.emotion_flag.in_(("SAD", "LOW", "RISK")),
            TalkSession.private_flag.is_(False),
        )
    ).all()
    if len({t.astimezone(TZ).date() for t in started}) < MOOD_LOW_DAYS:
        return
    sent = db.scalar(
        select(func.count())
        .select_from(Notification)
        .where(
            Notification.room_id == room.room_id,
            Notification.kind == "MOOD_LOW_2D",
            Notification.sent_at >= now_kst() - timedelta(days=MOOD_LOW_WINDOW_DAYS),
        )
    )
    if sent:
        return
    who = f"{room.elder_name} {room.elder_honorific}"
    body = f"{who}께서 요즘 기운이 없어 보이는 날이 있었어요. 무슨 말씀을 하셨는지는 전하지 않아요."
    notify_family(db, room.room_id, "MOOD_LOW_2D", LOW_DAYS_TITLE, body, "HOME_001")
    log.info("mood low days room=%s", room.room_id)


def _comforted(session: TalkSession) -> int:
    """이 대화에서 한 위로 말 수. 0 이 아니면 위로 중 — 질문 수·5분 상한을 따지지 않는다 (11/23)."""
    return sum(1 for t in session.turns if t.get("comfort"))


def _comfort(db, session: TalkSession, room: FamilyRoom, end: str | None = None) -> SessionOut:
    """힘든 말씀(마음 위급) 뒤 위로 (D94 바꿈, 11/23 사용자): 대화를 끝내지 않고 심심이가 위로를 잇는다.

    가족 알림·urgent_alerts 는 _note_mood 가 대화에 1번(위급 낱말 안전망도 AI 신호도). 어르신께는 '가족에게 알렸어요'를
    말하지 않는다. 위로 말을 COMFORT_TURNS 번 한 뒤의 답(또는 end — 무응답 끝)에는 마무리 인사로 끝낸다.
    일기 대화는 일기로 남기지 않는다(USER_STOP — 힘든 말이 그대로 일기가 되지 않게).
    """
    _note_mood(db, session, "RISK")
    n = _comforted(session) + 1
    if end or n > COMFORT_TURNS:
        reply = coach.COMFORT_CLOSING
        _add_turn(session, "AI", reply.text, question_type=reply.question_type, comfort=n)
        reason = end or ("USER_STOP" if session.kind == "DIARY" else "COMPLETED")
        _finish(db, session, reason)
        db.commit()
        return _out(db, session, room, reply, "ENDED", reason)
    t0 = time.perf_counter()
    reply = coach.comfort(coach_context(db, room, session), n)
    latency = int((time.perf_counter() - t0) * 1000)
    _add_turn(session, "AI", reply.text, question_type=reply.question_type, latency_ms=latency, comfort=n)
    _last_reply[session.session_id] = reply
    db.commit()
    return _out(db, session, room, reply)


def _body_close(db, session: TalkSession, room: FamilyRoom) -> SessionOut:
    """몸 위급 낱말(안전망, 11/19 응급): AI 를 부르지 않고 가족 모두에게 바로 알린 뒤 119 버튼과 함께 마무리한다.

    일기 대화·AI 가 실패한 턴도 잡는다. 일기 대화는 일기로 남기지 않는다(USER_STOP — _comfort 와 같다).
    """
    alerts.raise_alert(db, room, session.session_id, "BODY")
    log.info("body urgent room=%s session=%s", room.room_id, session.session_id)
    reply = coach.BODY_CLOSING
    _add_turn(session, "AI", reply.text, question_type=reply.question_type, urgent="BODY")
    reason = "USER_STOP" if session.kind == "DIARY" else "COMPLETED"
    _finish(db, session, reason)
    db.commit()
    return _out(db, session, room, reply, "ENDED", reason)


def _ai_out(db, session: TalkSession, room: FamilyRoom, reply: CoachReply) -> AiOut:
    audio_b64 = None
    try:
        audio = tts.synthesize(reply.text, float(room.tts_speed), room.tts_voice)
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
        care=_caring(session),
        face=getattr(reply, "face", None),  # 잡담만 (D106)
        go=getattr(reply, "go", None),
    )


def _caring(session: TalkSession) -> bool:
    """마지막 AI 말이 위로(또는 위로 끝인사)면 true — 화면이 심심이 위로 얼굴, 전화 버튼 없음 (11/23)."""
    return bool((_last_ai_turn(session) or {}).get("comfort"))


def _talk_seconds(session: TalkSession) -> float:
    """5분 상한용 '대화한 시간'. 시작·각 턴·지금 사이 간격을 PAUSE_GAP_SEC 까지만 더한다.

    더 긴 간격은 보류(전화·홈 버튼)로 보고 빼야 '30분 안 복귀'가 가능하다. 턴 시각이 turns 에 있어 칸 추가가 필요 없다.
    """
    times = [session.started_at, *_turn_times(session), now_kst()]
    return sum(min((b - a).total_seconds(), PAUSE_GAP_SEC) for a, b in zip(times, times[1:]))


def _expired(session: TalkSession) -> bool:
    limit = CHAT_SESSION_SEC if session.kind == "CHAT" else MAX_SESSION_SEC  # 잡담은 20분 (D106)
    return _talk_seconds(session) > limit + (MORE_SESSION_SEC if session.session_id in _more else 0)


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
        # 몸 위급으로 끝난 대화면 화면이 [119 전화하기]를 띄운다 — 마무리 턴에 남긴 표시를 읽는다 (다시 열어도 같게)
        urgent=(_last_ai_turn(session) or {}).get("urgent") if state == "ENDED" else None,
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
    resume_of = None
    if body.kind == "CHAT" and body.resume_of:  # '지난 이야기'에서 [이어서 하기] (D106)
        if chat.earlier_of(db, room.room_id, body.resume_of) is None:
            raise ApiError(404, "SESSION_NOT_FOUND", "지난 이야기를 찾을 수 없어요")
        resume_of = body.resume_of
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
        if body.kind == "DIARY" and photo.source == "ELDER_CAMERA" and photo.analyzed_at is None:
            # 방금 찍은 사진 — 옛 사진 일기(D58)·1번 질문 재료(D71)는 첫 질문 전에 분류가 있어야 돈다.
            # 상한(CLASSIFY_SYNC_SEC)을 넘거나 실패하면 분류 전 그대로 평소 일기 (어르신 카메라 사진은 다시 하지 않음)
            classify.classify(photo, timeout=CLASSIFY_SYNC_SEC)
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
    ctx = coach_context(db, room, session)
    # 그날 첫 회상 대화는 지난 대화의 이야기로 시작할 수 있다 (AI-07, D77). 물을 기억이 없으면 평소처럼 사진 질문
    reply = _ask_story(db, session, ctx) if session.kind == "MEMORY" else None
    if reply is None:
        reply, _ = _ask(db, session, ctx, resume_of=resume_of)  # 어르신 말 전이라 signal 은 늘 NONE (coach)
    db.commit()
    return _out(db, session, room, reply)


@router.get("", response_model=list[ChatItemOut])
def list_chats(device: CurrentDevice, db: DB, kind: Literal["CHAT"]):
    """'지난 이야기' 목록 (D106) — 잡담만, 최신 순. 한 잡담의 말은 GET /elder/sessions/{id} 의 turns 로 읽는다.
    회상·일기는 사진첩·지난 일기 화면이 따로 보여 주므로 kind=CHAT 만 받는다."""
    return [
        ChatItemOut(
            session_id=s.session_id,
            started_at=s.started_at,
            title=chat.title_of(s),
            elder_turns=sum(1 for t in s.turns if t.get("speaker") == "ELDER"),
        )
        for s in chat.recent(db, device.room_id)
    ]


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
            care=_caring(session),
            face=getattr(reply, "face", None),  # 잡담만 — 가자는 화면(go)은 다시 열 때 또 데려가지 않게 싣지 않는다
        )
        if reply
        else None,
        turn_no=session.turn_count,
        input_locked=_locked(session.session_id),
        turns=[TurnOut(speaker=t["speaker"], text=t["text"]) for t in session.turns],  # 이어서 할 때 지난 말풍선
    )


def _urgent_words(text: str) -> bool:
    return has_risk_words(text) or has_body_words(text)


def _urgent_close(db, session: TalkSession, room: FamilyRoom, body: TurnIn, text: str) -> SessionOut:
    """확인을 거치지 않은 저신뢰 음성에 위급 낱말이 있을 때 — 그 말을 낮은 신뢰도 그대로 남기고 위급으로 마무리 (S2).

    낮은 신뢰도 답은 주간 이야기·이야기 기억에 쓰이지 않는다(WEEKLY_STT_MIN).
    """
    _pending.pop(session.session_id, None)
    _save_elder(db, session, body, text)
    return _comfort(db, session, room) if has_risk_words(text) else _body_close(db, session, room)


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

    if _expired(session) and not _comforted(
        session
    ):  # 5분 상한 (D8). 방금 한 답은 저장한 뒤 마무리. 위로 중엔 안 끊는다
        text = (body.text or "").strip()
        if text and body.event is None and _unconfirmed(body) and _urgent_words(text):
            return _urgent_close(db, session, room, body, text)  # 잘 못 들은 말 속 위급 낱말 — 버리지 않는다 (S2)
        if text and body.event is None and not _unconfirmed(body):
            body, text, said_no = _confirmed(session, body, text)  # 확인 질문 뒤 '맞아요'면 맡긴 문장을
            if not said_no:
                _save_elder(db, session, body, text)
                if has_risk_words(text):
                    return _comfort(db, session, room)
                if has_body_words(text):
                    return _body_close(db, session, room)
        reply, signal = _ask(db, session, coach_context(db, room, session), end="LIMIT")
        if signal == "RISK":
            return _comfort(db, session, room)
        _finish(db, session, "LIMIT")
        db.commit()
        return _out(db, session, room, reply, "ENDED", "LIMIT")

    if body.event == "NO_RESPONSE":  # 무응답 3단계: 재질문 → 칩만 → 종료
        _pending.pop(session.session_id, None)  # 확인 질문에 답이 없으면 맡긴 문장은 버리고 원래 질문을 다시
        _no_response[session.session_id] += 1
        stage = _no_response[session.session_id]
        if stage >= NO_RESPONSE_END:
            if _comforted(session):  # 위로 중 무응답 — 질문 대화의 끝인사가 아니라 위로 끝인사로
                return _comfort(db, session, room, end="NO_RESPONSE")
            reply, _ = _ask(db, session, coach_context(db, room, session), end="NO_RESPONSE")
            _finish(db, session, "NO_RESPONSE")
            db.commit()
            return _out(db, session, room, reply, "ENDED", "NO_RESPONSE")
        last = _last_reply.get(session.session_id) or _fallback(session)
        mood_question = session.kind == "DIARY" and session.turn_count >= _max_turns(session)
        if session.kind == "CHAT":  # 잡담은 답 버튼이 없다 — 같은 말을 다시. 가자는 화면은 다시 데려가지 않는다 (D106)
            last = last.model_copy(update={"go": None}) if getattr(last, "go", None) else last
        elif stage >= 2 and not mood_question:  # 일기 기분 질문은 칩 4개 그대로 (둘만 남기면 기분이 한쪽으로 치우친다)
            last = last.model_copy(
                update={"choice_mode": "TWO_BUTTONS", "suggestions": (last.suggestions or ["네", "아니요"])[:2]}
            )
        db.commit()  # 저장할 것은 없다 — 세션 행 잠금을 여기서 푼다. 아래 _out 이 음성을 만드는 몇 초 동안 쥐지 않게
        return _out(db, session, room, last)

    text = (body.text or "").strip()
    if not text:
        raise ApiError(422, "TEXT_REQUIRED", "말씀 내용이 비어 있어요")
    if body.input_type == "VOICE" and _locked(session.session_id):
        if _urgent_words(text):  # 말하기가 잠긴 뒤에 온 음성이라도 위급한 말은 버리지 않는다 (11/19)
            return _urgent_close(db, session, room, body, text)
        raise ApiError(409, "INPUT_LOCKED", "지금은 버튼으로만 답할 수 있어요")
    if _unconfirmed(body) and _urgent_words(text):
        # 잘 못 들은 말이어도 위급 낱말이 있으면 되묻지 않고 바로 위급으로 본다 (11/19 S2). 되물으면 AI 가 그 말을
        # 되읽게 되고("제가 '죽고 싶어' 라고 들었어요"), '맞아요'가 없으면 알림 없이 사라진다.
        # 잘못 들은 말로 알림이 가는 쪽이, 진짜 위급을 놓치는 쪽보다 낫다
        return _urgent_close(db, session, room, body, text)
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
    if has_risk_words(text):  # 위급 낱말 안전망 — AI 판단을 기다리지 않는다 (D55 ①)
        return _comfort(db, session, room)
    if has_body_words(text):  # 몸 위급 낱말 안전망 — 일기 대화·AI 실패 때도 (11/19 응급)
        return _body_close(db, session, room)
    if _comforted(session):  # 위로 중 — 질문으로 돌아가지 않고 위로를 잇는다 (11/23)
        return _comfort(db, session, room)
    ctx = coach_context(db, room, session)
    _grant_more(session, text)  # '더 얘기할래' — 아래에서 끝내지 않고 질문을 더 한다
    if session.turn_count >= _max_turns(session):  # 마지막 답(회상·일기 5번째) → 마무리 인사 후 종료
        reply, signal = _ask(db, session, ctx, end="COMPLETED")
        if signal == "RISK":
            return _comfort(db, session, room)
        _finish(db, session, "COMPLETED")
        db.commit()
        return _out(db, session, room, reply, "ENDED", "COMPLETED")
    reply, signal = _ask(db, session, ctx, turn_no=session.turn_count + 1)
    if signal == "RISK":
        return _comfort(db, session, room)
    if signal in coach.ENDING_SIGNALS:  # 슬픔·위급·그만 (FR-AI-005, D55): 마무리 인사로 끝낸다. 질문 수는 그대로
        # 일기 대화가 위급으로 끝나면 일기로 남기지 않는다(USER_STOP) — 위급한 말이 그대로 일기가 되지 않게
        reason = "USER_STOP" if signal == "STOP" or session.kind == "DIARY" else "COMPLETED"
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
