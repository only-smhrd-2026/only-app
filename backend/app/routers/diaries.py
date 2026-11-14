"""어르신 일기: 초안(+그림일기) → '네, 올려요' 게시 → 가족 홈 '새 일기' (FR-DI-003~005, FR-FD-001·004 최소판, D36).

1. 일기 대화(sessions, kind=DIARY, 질문 3개)가 COMPLETED·LIMIT 로 끝남 (그만할래요·무응답·오류는 저장 안 함)
2. POST /elder/sessions/{id}/draft — 초안(1인칭 본문·기분·그릴 사물). 사진 없는 일기는 그림까지 기다렸다가 같이
   돌려준다 → 어르신은 확인 화면에서 그림을 보고 올린다. 그림이 실패하면 글만(NONE).
3. POST /elder/diaries — 초안 그대로 게시 + 가족 모두에게 DIARY_POSTED 앱 내 알림 1건씩.
   request_id·session_id 로 한 번만.
4. GET /rooms/{id}/diaries — 가족 홈(HOME_001) 목록. read_by_me=false 가 '새 일기'.
   실시간 반영은 없다(가족이 홈을 열 때 읽는다).
5. POST /diaries/{id}/read — 가족 '다 봤어요' 열람 기록(diaries.family_read_by). 여러 번 불러도 1번.
   어르신 가족 소식 '다 들었어요'는 기기 쿠키 전용 POST /elder/diaries/{id}/read
   (안 들은 소식 목록은 GET /elder/family-news).
6. POST /rooms/{id}/diaries — 가족 일기 올리기. 같은 가족방 + 같은 request_id 는 1개.
7. GET /diaries/{id} — 일기 한 건(HOME_002). 구성원만, 지워진 일기는 404.
8. GET /elder/diaries — 어르신 '내 일기' 목록(기기 쿠키). 어르신이 쓴 게시 일기만 최신 먼저.
9. POST /diaries/{id}/reaction — 가족 이모지(HEART·SMILE·CLAP)를 어르신 일기에. 본문 {kind, on} = 이 상태로 만듦
   (켜기·바꾸기·취소), 한 사람 1칸. POST /elder/diaries/{id}/like — 어르신 [좋아요]를 가족 일기에(기기 쿠키). 본문 {on}.
10. GET /elder/family-news 의 hearts — 어르신이 아직 못 들은 가족 이모지('하트가 왔어요' 첫 장, D63).
    읽어 드린 뒤 POST /elder/hearts/heard {until} 이 그때까지 온 칸에 heard_at 을 적는다.

담당: 일기 프롬프트·그림 화풍(image.STYLE) 다듬기 홍진성 / 사진 일기(카메라)·가족 일기·목록 세부 천주웅.
그림 제공자는 Workers AI FLUX.2 klein 4B 로 연결됨(D37, IMAGE_PROVIDER=cloudflare).
"""

from __future__ import annotations

import base64
import logging
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

from fastapi import APIRouter
from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.ai import coach, image, tts
from app.config import DIARY_DRAFT_MIN, ELDER_DIARY_LIST_LIMIT, ELDER_HEARTS_LIMIT, now_kst
from app.deps import DB, CurrentDevice, CurrentUser, require_member
from app.errors import ApiError
from app.models import Diary, FamilyRoom, Photo, RoomMember, User
from app.routers.devices import notify_family
from app.routers.sessions import DIARY_SAVED, _tts_failed, coach_context, load_session
from app.schemas.diaries import (
    DiaryCreateIn,
    DiaryListOut,
    DiaryOut,
    DraftOut,
    ElderDiaryIn,
    ElderLikeIn,
    FamilyNewsOut,
    HeartOut,
    HeartsHeardIn,
    ReactionIn,
)
from app.services import storage

log = logging.getLogger("app.diaries")
router = APIRouter(tags=["diaries"])


@dataclass
class _Draft:
    out: DraftOut
    draw_spec: dict | None
    illustration_key: str | None
    made_at: datetime


# ponytail: 초안은 프로세스 메모리에 30분 (uvicorn --workers 1 전제 D9, sessions._last_reply 와 같은 방식).
# 재시작하면 사라져 다시 만든다(글·그림이 바뀔 수 있음). 재시작에도 남겨야 하면 diary_drafts 테이블로.
_drafts: dict[uuid.UUID, _Draft] = {}
# 대화별 잠금: 초안 요청이 겹쳐도(두 번 탭·새로고침) LLM·그림은 한 번, 게시도 한 번.
# ponytail: 잠금은 지우지 않는다(대화 1개당 수십 바이트). 지우면 기다리던 요청과 새 요청이 서로 다른 잠금을 잡는다.
_locks: dict[uuid.UUID, threading.Lock] = {}
_locks_guard = threading.Lock()


def _lock(session_id: uuid.UUID) -> threading.Lock:
    with _locks_guard:
        return _locks.setdefault(session_id, threading.Lock())


def _cached(session_id: uuid.UUID) -> _Draft | None:
    """30분 안의 초안. 지난 초안은 이때 같이 정리한다."""
    old = now_kst() - timedelta(minutes=DIARY_DRAFT_MIN)
    for sid in [k for k, d in list(_drafts.items()) if d.made_at < old]:
        _drafts.pop(sid, None)
    return _drafts.get(session_id)


# ponytail: 올리지 않은 초안의 그림 파일은 저장소에 남는다(다시 말할래요·포기). 정리가 필요해지면 scheduler 에 잡 하나.
def _draw(room_id: int, session_id: uuid.UUID, draw_spec: dict) -> tuple[str, bytes] | None:
    """그림일기 1장을 그려 저장한다. 실패하면 None → 글만 게시 (D36, 11/5 사용자 결정)."""
    key = f"rooms/{room_id}/{session_id}.jpg"
    try:
        data = image.generate(draw_spec, draw_spec["seed"])
        if not data:
            return None
        storage.put(key, data)
    except Exception as e:  # 제공자 오류·시간 초과·저장 실패 모두 글만
        log.warning("draw failed session=%s type=%s", session_id, type(e).__name__)
        return None
    return key, data


MOOD_LABEL = {code: label for label, code in coach.DIARY_MOODS.items()}  # SUNNY → 맑음


def _speech(body: str, mood: str, room: FamilyRoom) -> tuple[str | None, bool]:
    """본문 + 기분 + '이대로 올릴까요?' 서버 TTS (ONLY_500). None 이면 화면이 같은 문장을 브라우저 TTS 로 읽는다 (D5).
    반환 (음성 base64, 실패했나). 문장을 바꾸면 ELDER_DIARY_003.tsx 의 readAloud 도 같이."""
    try:
        audio = tts.synthesize(
            f"{body} 오늘 기분은 {MOOD_LABEL[mood]}. 이대로 올릴까요?", float(room.tts_speed), room.tts_voice
        )
    except Exception as e:
        log.warning("tts failed type=%s", type(e).__name__)
        return None, True
    return (base64.b64encode(audio).decode() if audio else None), False


@router.post("/elder/sessions/{session_id}/draft", response_model=DraftOut)
def make_draft(session_id: uuid.UUID, device: CurrentDevice, db: DB):
    """일기 초안 (ELDER_DIARY_003). 사진 없는 일기는 그림까지 기다렸다 같이 준다. 30분 안에 다시 부르면 같은 초안."""
    session = load_session(db, session_id, device)
    if session.kind != "DIARY" or session.end_reason not in DIARY_SAVED:
        raise ApiError(409, "DIARY_NOT_READY", "일기로 쓸 이야기가 없어요")
    with _lock(session_id):
        # 이미 올린 대화로 다시 만들면 올린 그림 파일을 덮어쓴다 → 막는다
        if db.scalar(select(Diary.diary_id).where(Diary.session_id == session_id).limit(1)):
            raise ApiError(409, "DIARY_POSTED", "이미 가족들한테 보낸 일기예요")
        cached = _cached(session_id)
        if cached:
            return cached.out
        room = db.get(FamilyRoom, session.room_id)
        ctx = coach_context(db, room, session)
        if not any(t["speaker"] == "ELDER" for t in ctx.turns):
            raise ApiError(409, "DIARY_NOT_READY", "일기로 쓸 이야기가 없어요")
        draft = coach.diary_draft(ctx)
        photo = db.get(Photo, session.photo_id) if session.photo_id else None
        # 그릴 사물이 없으면 기분 그림. 시드는 대화 번호로 — 같은 사물·기분이 날마다 같은 그림이 되지 않게 (D69)
        objects = draft.draw_objects or image.MOOD_OBJECTS[draft.mood]
        draw_spec = None if photo else {"objects": objects, "seed": session_id.int % 2**31}
        drawn = _draw(room.room_id, session_id, draw_spec) if draw_spec else None
        audio_b64, failed = _speech(draft.body, draft.mood, room)
        if failed and session_id not in _tts_failed:  # 낭독 실패도 가족 알림은 대화에 1건 (D5, _ai_out 과 같이)
            _tts_failed.add(session_id)
            notify_family(db, room.room_id, "TTS_ERROR", f"{room.elder_name} 님 기기에서 음성 재생에 문제가 있어요")
            db.commit()
        out = DraftOut(
            session_id=session_id,
            body=draft.body,
            mood=draft.mood,
            photo_id=session.photo_id,
            illustration_type="PHOTO" if photo else ("AI_DRAWING" if drawn else "NONE"),
            illustration_url=f"/api/media/{photo.object_key}" if photo else None,
            illustration_b64=base64.b64encode(drawn[1]).decode() if drawn else None,
            audio_b64=audio_b64,
        )
        _drafts[session_id] = _Draft(out, draw_spec, drawn[0] if drawn else None, now_kst())
        return out


def _member_names(db, room_id: int) -> dict[int, str]:
    """가족방 사람의 user_id → 별명(없으면 이름). 방에서 나간 사람도 그 줄은 남아 있어 이름이 나온다."""
    rows = db.execute(
        select(RoomMember.user_id, RoomMember.nickname, User.name)
        .join(User, User.user_id == RoomMember.user_id)
        .where(RoomMember.room_id == room_id)
    ).all()
    return {user_id: nickname or name for user_id, nickname, name in rows}


def _elder_diaries_with_reactions(room_id: int):
    return select(Diary).where(
        Diary.room_id == room_id,
        Diary.author_type == "ELDER",
        Diary.status == "POSTED",
        func.jsonb_array_length(Diary.reactions) > 0,
    )


def _unheard(reaction: dict) -> bool:
    return reaction.get("by") == "FAMILY" and "heard_at" not in reaction


def unheard_hearts(db, room_id: int) -> list[tuple[Diary, dict]]:
    """어르신이 아직 못 들은 가족 이모지 (일기, 칸), 받은 순서. 가족 소식 첫 장과 홈 숫자(elder.py)가 쓴다 (D63)."""
    # ponytail: 리액션이 달린 어르신 일기를 읽어 코드로 거른다(일기는 하루 한두 편). 느려지면 jsonb_path_exists 조건으로
    diaries = db.scalars(_elder_diaries_with_reactions(room_id)).all()
    found = [(diary, r) for diary in diaries for r in diary.reactions if _unheard(r)]
    return sorted(found, key=lambda pair: pair[1]["at"])


def _rows(db, room: FamilyRoom, *cond, me: int | None = None, limit: int = 50) -> list[DiaryOut]:
    """일기 행 → DiaryOut (최근 limit 개, 기본 50). me = 보는 가족 user_id, None 이면 어르신 기기가 보는 것."""
    rows = db.execute(
        select(Diary, User.name, Photo.object_key, RoomMember.nickname)
        .outerjoin(User, User.user_id == Diary.author_user_id)
        .outerjoin(Photo, Photo.photo_id == Diary.photo_id)
        # 쓴 사람의 가족방 별명. (room_id, user_id) 는 한 줄뿐이라 일기가 겹쳐 나오지 않는다.
        # 방에서 나간 사람도 그 줄은 남아 있다
        .outerjoin(RoomMember, and_(RoomMember.room_id == Diary.room_id, RoomMember.user_id == Diary.author_user_id))
        .where(Diary.room_id == room.room_id, Diary.status == "POSTED", *cond)
        .order_by(Diary.posted_at.desc(), Diary.diary_id.desc())
        .limit(limit)
    ).all()
    # 리액션을 누른 가족의 이름은 응답에만 붙인다 (DB 에는 user_id 만)
    names = _member_names(db, room.room_id) if any(d.reactions for d, *_ in rows) else {}
    out = []
    for d, name, photo_key, nickname in rows:
        mine = d.author_user_id == me if me is not None else d.author_type == "ELDER"
        by_elder = d.elder_read_at is not None
        by_me = me in d.family_read_by if me is not None else by_elder
        key = photo_key if d.illustration_type == "PHOTO" else d.illustration_key
        out.append(
            DiaryOut(
                diary_id=d.diary_id,
                room_id=d.room_id,
                author_type=d.author_type,
                author_name=f"{room.elder_name} {room.elder_honorific}" if d.author_type == "ELDER" else name,
                author_nickname=nickname if d.author_type == "FAMILY" else None,
                body=d.body,
                mood=d.mood,
                illustration_type=d.illustration_type,
                illustration_url=f"/api/media/{key}" if key else None,
                posted_at=d.posted_at,
                read_by_elder=by_elder,
                read_by_me=mine or by_me,
                reactions=[
                    dict(r, name=names.get(r.get("user_id")) if r.get("by") == "FAMILY" else None) for r in d.reactions
                ],
            )
        )
    return out


@router.post("/elder/diaries", response_model=DiaryOut, status_code=201)
def post_elder_diary(body: ElderDiaryIn, device: CurrentDevice, db: DB):
    """'네, 올려요' (FR-DI-004). 초안 그대로 게시 + 가족 모두에게 알림 1건씩. 다시 눌러도 일기 1개·알림 1번."""
    room = db.get(FamilyRoom, device.room_id)
    session = load_session(db, body.session_id, device)
    with _lock(session.session_id):
        done = db.scalar(
            select(Diary.diary_id)
            .where(
                Diary.room_id == room.room_id,
                or_(Diary.request_id == body.request_id, Diary.session_id == session.session_id),
            )
            .limit(1)
        )
        if done:  # 응답을 못 받아 다시 누른 경우: 같은 일기를 돌려주고 알림은 다시 보내지 않는다
            return _rows(db, room, Diary.diary_id == done)[0]
        draft = _cached(session.session_id)
        if not draft:
            raise ApiError(409, "DRAFT_EXPIRED", "시간이 지나서 일기를 다시 써야 해요")
        d = draft.out
        diary = Diary(
            room_id=room.room_id,
            author_type="ELDER",
            session_id=session.session_id,
            photo_id=d.photo_id,
            body=d.body,
            mood=d.mood,
            illustration_type=d.illustration_type,
            illustration_key=draft.illustration_key,
            draw_spec=draft.draw_spec,
            request_id=body.request_id,
        )
        db.add(diary)
        title = f"{room.elder_name} {room.elder_honorific} 일기가 왔어요"
        notify_family(db, room.room_id, "DIARY_POSTED", title, body=d.body[:100], link="HOME_001")
        db.commit()
        _drafts.pop(session.session_id, None)
    return _rows(db, room, Diary.diary_id == diary.diary_id)[0]


@router.post("/rooms/{room_id}/diaries", response_model=DiaryOut, status_code=201)
def post_family_diary(room_id: int, body: DiaryCreateIn, user: CurrentUser, db: DB):
    """가족 일기 올리기 (FR-DI-008). 여러 가족방은 화면이 방마다 같은 request_id 로 한 번씩 부른다.

    같은 가족방 + 같은 request_id 는 일기 1개(uq_diaries_room_id_request_id). 두 번 와도 같은 일기를 돌려준다.
    일기 동무(AI 다듬기)는 아직 없어 받은 글 그대로 저장한다. 알림은 없다(요구사항 '푸시 없음').
    """
    require_member(room_id, user, db)
    text = body.body.strip()
    if not text:
        raise ApiError(422, "VALIDATION", "일기 내용을 적어 주세요")
    if body.photo_id is not None:
        photo = db.get(Photo, body.photo_id)
        if photo is None or photo.room_id != room_id or photo.status != "ACTIVE":  # 남의 가족방 사진은 못 붙인다
            raise ApiError(404, "PHOTO_NOT_FOUND", "사진을 찾을 수 없어요")
    # session_id 는 저장하지 않는다(어르신 대화용 칸). illustration_type 은 요청 값을 믿지 않고 서버가 정한다
    db.execute(
        pg_insert(Diary)
        .values(
            room_id=room_id,
            author_type="FAMILY",
            author_user_id=user.user_id,
            photo_id=body.photo_id,
            body=text,
            mood=body.mood,
            illustration_type="PHOTO" if body.photo_id is not None else "NONE",
            request_id=body.request_id,
        )
        .on_conflict_do_nothing(constraint="uq_diaries_room_id_request_id")
    )
    db.commit()
    diary_id = db.scalar(select(Diary.diary_id).where(Diary.room_id == room_id, Diary.request_id == body.request_id))
    rows = _rows(db, db.get(FamilyRoom, room_id), Diary.diary_id == diary_id, me=user.user_id)
    if not rows:  # 지워진 일기의 request_id 로 다시 온 경우
        raise ApiError(404, "DIARY_NOT_FOUND", "일기를 찾을 수 없어요")
    log.info("family diary room=%s diary=%s", room_id, diary_id)
    return rows[0]


@router.get("/rooms/{room_id}/diaries", response_model=DiaryListOut)
def list_diaries(room_id: int, user: CurrentUser, db: DB):
    """가족 홈 일기 목록 최소판 (FR-FD-001) — 최근 50개. 페이지·어르신 칩·가족 일기 세부는 천주웅."""
    require_member(room_id, user, db)
    return DiaryListOut(diaries=_rows(db, db.get(FamilyRoom, room_id), me=user.user_id))


@router.get("/elder/diaries", response_model=DiaryListOut)
def elder_my_diaries(device: CurrentDevice, db: DB):
    """어르신 사진첩 '내 일기' (ELDER_ALBUM_001 ④, FR-DI-004). 이 가족방에서 어르신이 쓴 게시 일기만 최신 먼저."""
    room = db.get(FamilyRoom, device.room_id)
    return DiaryListOut(diaries=_rows(db, room, Diary.author_type == "ELDER", limit=ELDER_DIARY_LIST_LIMIT))


@router.get("/elder/family-news", response_model=FamilyNewsOut)
def elder_family_news(device: CurrentDevice, db: DB):
    """어르신이 아직 안 들은 이 가족방의 가족 일기, 최근 50개 (FR-FD-003) + 아직 못 들은 가족 이모지 (D63).

    홈의 안 들은 소식 수(elder.py home)와 같은 조건. 50개가 넘으면 들은 뒤 다시 부를 때 나머지가 나온다.
    hearts 는 가족 소식 첫 장 '하트가 왔어요' — 받은 순서. 읽어 드린 뒤 POST /elder/hearts/heard.
    """
    room = db.get(FamilyRoom, device.room_id)
    names = _member_names(db, room.room_id)
    hearts = [
        HeartOut(diary_id=diary.diary_id, kind=r["kind"], name=names.get(r.get("user_id")), at=r["at"])
        for diary, r in unheard_hearts(db, room.room_id)[:ELDER_HEARTS_LIMIT]
    ]
    return FamilyNewsOut(
        diaries=_rows(db, room, Diary.author_type == "FAMILY", Diary.elder_read_at.is_(None)), hearts=hearts
    )


@router.post("/elder/diaries/{diary_id}/read", status_code=204)
def elder_mark_read(diary_id: int, device: CurrentDevice, db: DB):
    """어르신 '다 들었어요'. 첫 열람 시각만 기록하고 다른 가족방 일기는 숨긴다 (FR-FD-004)."""
    diary = db.get(Diary, diary_id)
    if diary is None or diary.room_id != device.room_id or diary.author_type != "FAMILY" or diary.status != "POSTED":
        raise ApiError(404, "DIARY_NOT_FOUND", "일기를 찾을 수 없어요")
    db.execute(
        update(Diary).where(Diary.diary_id == diary_id, Diary.elder_read_at.is_(None)).values(elder_read_at=now_kst())
    )
    db.commit()


@router.post("/elder/diaries/{diary_id}/like", response_model=DiaryOut)
def elder_like(diary_id: int, body: ElderLikeIn, device: CurrentDevice, db: DB):
    """어르신 [좋아요]를 가족 일기에 (D54). 본문 {on} = '이 상태로 만들어 줘' — 두 번 와도 같다. 기기 쿠키 전용."""
    diary = db.get(Diary, diary_id, with_for_update=True)  # 같은 순간의 다른 리액션과 서로 덮어쓰지 않게
    if diary is None or diary.room_id != device.room_id or diary.status != "POSTED":
        raise ApiError(404, "DIARY_NOT_FOUND", "일기를 찾을 수 없어요")
    if diary.author_type != "FAMILY":  # 404 확인 뒤에 — 먼저 하면 남의 가족방에 어떤 일기가 있는지 드러난다
        raise ApiError(409, "REACTION_NOT_ALLOWED", "좋아요는 가족 일기에만 누를 수 있어요")
    liked = any(r.get("by") == "ELDER" for r in diary.reactions)
    if body.on and not liked:
        # 새 리스트를 통째로 넣어야 저장된다. 어르신 칸에는 user_id 키를 넣지 않는다
        diary.reactions = [*diary.reactions, {"by": "ELDER", "kind": "LIKE", "at": now_kst().isoformat()}]
    elif not body.on and liked:
        diary.reactions = [r for r in diary.reactions if r.get("by") != "ELDER"]
    db.commit()  # 바뀐 게 없어도 — 행 잠금이 풀린다
    return _rows(db, db.get(FamilyRoom, device.room_id), Diary.diary_id == diary_id)[0]


@router.post("/elder/hearts/heard", status_code=204)
def elder_hearts_heard(body: HeartsHeardIn, device: CurrentDevice, db: DB):
    """가족 소식 첫 장을 들으셨다 — until 까지 온 가족 이모지에 들은 시각을 적는다 (D63).

    그 뒤에 온 것은 다음에 읽어 드린다(듣는 사이에 온 하트가 읽히지 않은 채 '들음'이 되지 않게).
    여러 번 불러도 처음 들은 시각 그대로.
    """
    now = now_kst().isoformat()

    def due(reaction: dict) -> bool:
        return _unheard(reaction) and datetime.fromisoformat(reaction["at"]) <= body.until

    # 행 잠금 — 같은 순간의 가족 이모지(send_reaction)와 서로 덮어쓰지 않게
    for diary in db.scalars(_elder_diaries_with_reactions(device.room_id).with_for_update()).all():
        if any(due(r) for r in diary.reactions):
            diary.reactions = [dict(r, heard_at=now) if due(r) else r for r in diary.reactions]
    db.commit()


@router.get("/diaries/{diary_id}", response_model=DiaryOut)
def get_diary(diary_id: int, user: CurrentUser, db: DB):
    """일기 한 건 (HOME_002, FR-FD-002). 목록과 같은 모양. 읽기만 하고 '봤어요'는 POST /diaries/{id}/read 가 한다."""
    diary = db.get(Diary, diary_id)
    member = diary is not None and db.scalar(
        select(RoomMember.member_id).where(
            RoomMember.room_id == diary.room_id,
            RoomMember.user_id == user.user_id,
            RoomMember.removed_at.is_(None),
        )
    )
    if not member or diary.status != "POSTED":  # 다른 방 일기도 없는 것처럼 404 (D43)
        raise ApiError(404, "DIARY_NOT_FOUND", "일기를 찾을 수 없어요")
    return _rows(db, db.get(FamilyRoom, diary.room_id), Diary.diary_id == diary_id, me=user.user_id)[0]


@router.post("/diaries/{diary_id}/read", status_code=204)
def mark_read(diary_id: int, user: CurrentUser, db: DB):
    """가족 '다 봤어요' 열람 기록 (diaries.family_read_by 에 내 user_id, FR-FD-004). 여러 번 불러도 1번.

    가족 쿠키 전용. 어르신 기록은 기기 쿠키 전용 /elder/diaries/{id}/read 로 나눈다 — 한 브라우저에 두 쿠키가
    다 있으면(가족이 어르신 폰을 연결해 준 경우) 누가 읽었는지 섞이기 때문.
    """
    diary = db.get(Diary, diary_id)
    member = diary is not None and db.scalar(
        select(RoomMember.member_id).where(
            RoomMember.room_id == diary.room_id,
            RoomMember.user_id == user.user_id,
            RoomMember.removed_at.is_(None),
        )
    )
    if not member or diary.status != "POSTED":  # 다른 방 일기도 없는 것처럼 404 (존재 여부 비노출, D18)
        raise ApiError(404, "DIARY_NOT_FOUND", "일기를 찾을 수 없어요")
    # 이미 들어 있으면 고치지 않는 UPDATE 한 문장 → 두 번 눌러도·동시에 와도 한 번만 (D38)
    db.execute(
        update(Diary)
        .where(Diary.diary_id == diary_id, ~Diary.family_read_by.contains([user.user_id]))
        .values(family_read_by=Diary.family_read_by.op("||")(func.jsonb_build_array(user.user_id)))
    )
    db.commit()


@router.post("/diaries/{diary_id}/reaction", response_model=DiaryOut)
def send_reaction(diary_id: int, body: ReactionIn, user: CurrentUser, db: DB):
    """가족 이모지를 어르신 일기에 (D54). 본문 {kind, on} = '이 상태로 만들어 줘' — 켜기·바꾸기·취소, 한 사람 1칸.

    같은 요청이 두 번 와도 결과가 같다. 가족 쿠키 전용(mark_read 와 같은 이유로 어르신 주소와 나눈다).
    """
    diary = db.get(Diary, diary_id, with_for_update=True)  # 두 가족이 동시에 눌러도 서로의 칸을 덮어쓰지 않게
    member = diary is not None and db.scalar(
        select(RoomMember.member_id).where(
            RoomMember.room_id == diary.room_id,
            RoomMember.user_id == user.user_id,
            RoomMember.removed_at.is_(None),
        )
    )
    if not member or diary.status != "POSTED":  # 다른 방 일기도 없는 것처럼 404 (D43)
        raise ApiError(404, "DIARY_NOT_FOUND", "일기를 찾을 수 없어요")
    if diary.author_type != "ELDER":  # 404 확인 뒤에 — 먼저 하면 남의 가족방에 어떤 일기가 있는지 드러난다
        raise ApiError(409, "REACTION_NOT_ALLOWED", "이모지는 어르신 일기에만 보낼 수 있어요")
    mine = next((r for r in diary.reactions if r.get("by") == "FAMILY" and r.get("user_id") == user.user_id), None)
    others = [r for r in diary.reactions if r is not mine]
    same = mine is not None and mine.get("kind") == body.kind
    if body.on and not same:  # 없던 것을 켜거나 다른 이모지에서 바꿔 끼움. 새 리스트를 통째로 넣어야 저장된다
        new = {"by": "FAMILY", "user_id": user.user_id, "kind": body.kind, "at": now_kst().isoformat()}
        diary.reactions = [*others, new]
    elif not body.on and same:  # 켜져 있는 그 이모지만 끈다. 다른 이모지로 바뀌어 있으면 이미 꺼진 상태
        diary.reactions = others
    db.commit()  # 바뀐 게 없어도 — 행 잠금이 풀린다
    return _rows(db, db.get(FamilyRoom, diary.room_id), Diary.diary_id == diary_id, me=user.user_id)[0]
