"""가족 홈 마음 카드: 최근 한국 날짜별 활동·기분만 집계한다.

마음 체크는 마지막 결과의 날짜·단계만(점수 없음). 어르신 마음 체크 초대 여부·답 저장(기기 쿠키, D56).
11/23 '내 마음': 체크(PHQ9 기분·UCLA3 외로움·GAD7 걱정·SMCQ 기억력) + 기억력 놀이(MEMGAME).
11/25 기분 = PHQ-9 9문항 하나로(사용자). 예전 PHQ8 결과는 그대로 읽는다.
어르신께는 결과를 점수 없이 얼굴·말로(NFR-DE-003), 가족 홈에는 PHQ8·PHQ9 만 보인다.
"""

from datetime import datetime, time, timedelta

from fastapi import APIRouter
from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.config import (
    MOOD_CHECK_DOWN_MIN,
    MOOD_CHECK_EVERY_DAYS,
    MOOD_CHECK_HARD_MIN,
    MOOD_HISTORY_LIMIT,
    MOOD_WEEK_DAYS,
    TZ,
    now_kst,
    today_kst,
)
from app.deps import DB, CurrentDevice, CurrentUser, require_member
from app.models import ELDER_SPOKE, Diary, FamilyRoom, MoodCheck, TalkSession
from app.routers.devices import notify_family
from app.schemas.mood import (
    MoodCheckDueOut,
    MoodCheckIn,
    MoodCheckOut,
    MoodCheckSavedOut,
    MoodDayOut,
    MoodHistoryItem,
    MoodHistoryOut,
    MoodOtherOut,
    MoodWeekOut,
)
from app.services import alerts, care, picks

router = APIRouter(tags=["mood"])

PHQ = ("PHQ8", "PHQ9")  # 가족 홈·돌봄 일지·주간 이야기·'할 차례'가 보는 종류 (11/23)
OTHER_KINDS = ("UCLA3", "GAD7", "SMCQ", "MEMGAME")  # 가족 홈에는 마지막 결과(얼굴·말)만 (11/23 사용자)
LOW_DAYS_TITLE = "안부 전화 어떠세요?"  # MOOD_LOW_2D 제목 (D55 ② 바꿈, 11/23)

# 결과 문장 — 시안(설계자료/목업_1120/src/app.js)의 TESTS[…].res()·moodResult() 와 같은 글자 (11/23).
# 단계(USUAL·DOWN·HARD)마다 (얼굴, 제목, 덧붙임)
RESULTS = {
    "PHQ": (
        ("😊", "요즘 마음이 괜찮으세요", ""),
        ("😐", "요즘 조금 지치셨어요", ""),
        ("😢", "요즘 많이 힘드셨군요", ""),
    ),
    "UCLA3": (
        ("😊", "외로움을 잘 이겨 내고 계세요", ""),
        ("😐", "가끔 쓸쓸하셨군요", "가족 소식을 자주 들려 드릴게요."),
        ("😔", "요즘 많이 쓸쓸하셨군요", "심심이가 자주 말 걸게요."),
    ),
    "GAD7": (
        ("😊", "요즘 마음이 편안하세요", ""),
        ("😐", "가끔 걱정이 많으셨군요", "걱정되는 일은 심심이한테 말씀해 주세요."),
        ("😟", "요즘 걱정이 많으셨군요", "심심이랑 이야기 나눠요."),
    ),
    "SMCQ": (
        ("😊", "기억력이 괜찮으세요", "기억력 놀이로 계속 지켜요."),
        ("😐", "가끔 깜빡하시는군요", "기억력 놀이를 자주 해 봐요."),
        # 보건소 문구는 뺐다 (11/25 사용자)
        ("🤔", "깜빡하는 일이 많으셨군요", "심심이랑 자주 이야기하고 기억력 놀이도 해 봐요."),
    ),
}
# 공식 채점 합에서 (DOWN 시작, HARD 시작)
# - PHQ-8·PHQ-9 (Kroenke 2001·2009): 문항 0~3 합. 5 가벼움 · 10 중간 — config 상수
# - GAD-7 (Spitzer 2006): 문항 0~3 합. 5 가벼움 · 10 중간
# - UCLA-3 (Hughes 2004): 문항 1~3점(화면 값+1) 합 3~9. 구간은 시안(화면 값 합 ≤1·≤3) 그대로 → 공식 점수 5·7.
#   (Steptoe 2013 은 6 이상을 '외로움'으로 본다 — 시안의 가운데 단계 5~6 과 걸친다)
# - SMCQ (Youn 2009, 주관적 기억감퇴 설문): 네 = 1 합 0~14. 구간은 시안(≤3·≤7) 그대로 → 4·8
BANDS = {"PHQ": (MOOD_CHECK_DOWN_MIN, MOOD_CHECK_HARD_MIN), "GAD7": (5, 10), "UCLA3": (5, 7), "SMCQ": (4, 8)}
LEVELS = ("USUAL", "DOWN", "HARD")
# PHQ 결과의 덧붙임 — 가장 높게 답한 문항 하나를 쉬운 말로 (시안 EASY, PHQ-9 의 9번은 쓰지 않는다)
EASY = (
    "즐거운 일이 줄었어요",
    "기분이 가라앉은 날이 있었어요",
    "잠을 잘 못 주무셨어요",
    "기운이 없으셨어요",
    "입맛이 없으셨어요",
    "스스로를 탓하신 날이 있었어요",
    "집중이 잘 안 되셨어요",
    "몸이 무거우셨어요",
)
# PHQ-9 9번(자해·죽음 생각)에 '있었다'고 하셨을 때 — 가족에게 알린다는 말은 하지 않는다 (11/23 사용자)
# 11/25 사용자: 기분 체크가 늘 9번을 물으니 109(자살예방 상담전화, 24시간)를 말과 버튼으로 알린다
# — D82 '상담 전화 버튼 없음'을 바꿈
ITEM9_SAY = (
    "말씀해 주셔서 고마워요. 많이 힘드셨겠어요. 심심이가 곁에 있을게요. "
    "힘드실 땐 109 에 전화하시면 언제든 이야기를 들어 드려요."
)


def score(kind: str, answers: list[int]) -> int:
    """공식 채점 합. UCLA-3 만 화면 값(0~2)에 1을 더한 1~3점 문항이다. 기억력 놀이는 맞힌 수."""
    return sum(answers) + (len(answers) if kind == "UCLA3" else 0)


def check_level(total: int, kind: str = "PHQ8") -> str:
    if kind == "MEMGAME":  # 맞힌 수가 많을수록 평소 — 3·2 평소, 1 조금, 0 많이
        return "USUAL" if total >= 2 else "DOWN" if total == 1 else "HARD"
    down, hard = BANDS["PHQ" if kind in PHQ else kind]
    return "HARD" if total >= hard else "DOWN" if total >= down else "USUAL"


def item9(kind: str, answers: list[int]) -> bool:
    return kind == "PHQ9" and answers[8] > 0


def result(kind: str, answers: list[int]) -> tuple[str, str, str]:
    """(얼굴, 제목, 덧붙임) — 점수·단계 이름 없이. 저장한 답으로 다시 만들 수 있어 따로 저장하지 않는다."""
    total = score(kind, answers)
    if kind == "MEMGAME":
        title = "세 개 다 기억하셨어요!" if total == 3 else f"세 개 중 {total}개 기억하셨어요"
        return "😊", title, "내일 또 해 봐요."  # 놀이라 몇 개를 맞히셨든 웃는 얼굴
    level = LEVELS.index(check_level(total, kind))
    if item9(kind, answers):  # 점수가 낮아도 9번이 있으면 가장 힘든 단계의 말로
        level = 2
    face, title, sub = RESULTS["PHQ" if kind in PHQ else kind][level]
    if kind in PHQ:
        first8 = answers[:8]
        top = max(first8)
        easy = f"{EASY[first8.index(top)]}." if top > 0 else ""
        sub = f"{easy} 심심이랑 이야기 나눠요.".strip() if level == 2 else easy
    return face, title, sub


def last_check_date(db: Session, room_id: int):
    """마지막 마음 체크(PHQ8·PHQ9) 날짜. 외로움·걱정·기억력 체크는 '할 차례'를 늦추지 않는다."""
    return db.scalar(
        select(func.max(MoodCheck.check_date)).where(MoodCheck.room_id == room_id, MoodCheck.kind.in_(PHQ))
    )


def check_due(db: Session, room_id: int) -> bool:
    """마음 체크 할 차례인지 — GET /elder/mood-check 와 어르신 홈 mood_due 가 같이 쓴다."""
    today = today_kst()
    last = last_check_date(db, room_id)
    if last and today - last < timedelta(days=MOOD_CHECK_EVERY_DAYS):
        return False
    pick = picks.today_pick(db, room_id, today)
    return pick is None or pick.status != "PENDING"


@router.get("/rooms/{room_id}/mood-week", response_model=MoodWeekOut)
def mood_week(room_id: int, user: CurrentUser, db: DB):
    require_member(room_id, user, db)
    today = today_kst()
    first = today - timedelta(days=MOOD_WEEK_DAYS - 1)
    since = datetime.combine(first, time.min, tzinfo=TZ)
    talked_dates = set()
    low_dates = set()
    for started_at, emotion_flag, private_flag in db.execute(
        select(TalkSession.started_at, TalkSession.emotion_flag, TalkSession.private_flag).where(
            TalkSession.room_id == room_id, TalkSession.started_at >= since, ELDER_SPOKE
        )
    ):
        day = started_at.astimezone(TZ).date()
        talked_dates.add(day)
        # SAD(11/12 전 값)·LOW·RISK 모두 기운 없는 날. '가족에게 말하지 마'라고 하신 대화는 빼되 위급은 그대로 (D55 ③)
        if emotion_flag != "NONE" and (emotion_flag == "RISK" or not private_flag):
            low_dates.add(day)
    moods = {}
    for posted_at, mood in db.execute(
        select(Diary.posted_at, Diary.mood)
        .where(
            Diary.room_id == room_id, Diary.author_type == "ELDER", Diary.status == "POSTED", Diary.posted_at >= since
        )
        .order_by(Diary.posted_at, Diary.diary_id)
    ):
        moods[posted_at.astimezone(TZ).date()] = mood
    days = []
    for offset in range(MOOD_WEEK_DAYS):
        day = first + timedelta(days=offset)
        days.append(MoodDayOut(date=day, talked=day in talked_dates, diary_mood=moods.get(day), low=day in low_dates))
    check = db.execute(
        select(MoodCheck.check_date, MoodCheck.level)
        .where(MoodCheck.room_id == room_id, MoodCheck.kind.in_(PHQ))
        .order_by(MoodCheck.check_date.desc(), MoodCheck.check_id.desc())
        .limit(1)
    ).first()
    last_check = MoodCheckOut(check_date=check.check_date, level=check.level) if check else None
    # 외로움·걱정·기억력 체크·기억력 놀이는 종류마다 마지막 결과를 얼굴·말로만 (11/23 사용자)
    others: dict[str, MoodOtherOut] = {}
    for kind, check_date, answers in db.execute(
        select(MoodCheck.kind, MoodCheck.check_date, MoodCheck.answers)
        .where(MoodCheck.room_id == room_id, MoodCheck.kind.in_(OTHER_KINDS))
        .order_by(MoodCheck.check_date.desc(), MoodCheck.check_id.desc())
    ):
        if kind not in others:
            face, title, _ = result(kind, answers)
            others[kind] = MoodOtherOut(kind=kind, check_date=check_date, face=face, title=title)
    last_talk_at = db.scalar(
        select(func.max(TalkSession.started_at)).where(TalkSession.room_id == room_id, ELDER_SPOKE)
    )
    return MoodWeekOut(
        days=days,
        talked_days=sum(day.talked for day in days),
        low_days=sum(day.low for day in days),
        last_check=last_check,
        other_checks=[others[k] for k in OTHER_KINDS if k in others],
        last_talk_at=last_talk_at,
    )


@router.get("/elder/mood-check", response_model=MoodCheckDueOut)
def mood_check_due(device: CurrentDevice, db: DB):
    return MoodCheckDueOut(due=check_due(db, device.room_id))


@router.post("/elder/mood-check", response_model=MoodCheckSavedOut)
def save_mood_check(body: MoodCheckIn, device: CurrentDevice, db: DB):
    kind, answers = body.kind, body.answers
    total = score(kind, answers)
    level = check_level(total, kind)
    saved = db.execute(
        pg_insert(MoodCheck)
        .values(room_id=device.room_id, check_date=today_kst(), kind=kind, answers=answers, total=total, level=level)
        .on_conflict_do_nothing(constraint="uq_mood_checks_room_id_check_date_kind")
        .returning(MoodCheck.check_id)
    ).scalar_one_or_none()
    room = db.get(FamilyRoom, device.room_id)
    who = f"{room.elder_name} {room.elder_honorific}"
    # 가족 알림은 그날 그 종류가 처음 저장될 때만 — 다시 보내도 1건 (11/19 S9)
    if saved is not None and item9(kind, answers):
        # PHQ-9 9번(자해·죽음 생각) — 대화의 위급과 같은 급한 알림 1건(가족 홈 긴급 카드·폰 알림, 30분 되풀이 막기).
        # 무엇을 답하셨는지는 넣지 않는다. 어르신께는 알렸다고 말하지 않는다 (11/23 사용자)
        alerts.raise_alert(db, room, None, "MOOD")
    elif saved is not None and level == "HARD" and kind in PHQ:
        # 가족이 마음 카드를 열어 보지 않아도 알게. 무엇을 답하셨는지·점수는 넣지 않는다.
        # 종류는 '기운 없는 날' 알림과 같이 써서(MOOD_LOW_2D) 같은 주에 '안부 전화' 알림이 겹치지 않는다 (D55 ②)
        body_text = f"{who}께서 마음 체크에서 요즘 많이 힘들다고 답하셨어요. 무엇을 답하셨는지는 전하지 않아요."
        notify_family(db, room.room_id, "MOOD_LOW_2D", LOW_DAYS_TITLE, body_text, "HOME_001")
    if kind in PHQ:  # 가족에게 한 줄로 알린다는 동의는 마음 체크(초대)에서만 듣는다 (D56)
        db.execute(
            update(FamilyRoom)
            .where(FamilyRoom.room_id == device.room_id, FamilyRoom.mood_check_consent_at.is_(None))
            .values(mood_check_consent_at=now_kst())
        )
    db.commit()
    face, title, sub = result(kind, answers)
    if item9(kind, answers):
        say = ITEM9_SAY
    elif kind in PHQ:
        # 끝 인사: 높게 답한 문항 하나를 쉬운 말로 받아 드린다 — 점수·단계는 말하지 않는다 (11/19 멘토링)
        say = care.check_say(answers[:8], hard=level == "HARD")
    else:
        say = None  # 화면이 제목·덧붙임을 읽는다
    return MoodCheckSavedOut(say=say, face=face, title=title, sub=sub, help_call=item9(kind, answers))


@router.get("/elder/mood-history", response_model=MoodHistoryOut)
def mood_history(device: CurrentDevice, db: DB):
    """어르신 '내 마음'의 지난 결과 — 최근 MOOD_HISTORY_LIMIT 개, 점수 없이 얼굴·말 (11/23)."""
    rows = db.scalars(
        select(MoodCheck)
        .where(MoodCheck.room_id == device.room_id)
        .order_by(MoodCheck.check_date.desc(), MoodCheck.check_id.desc())
        .limit(MOOD_HISTORY_LIMIT)
    ).all()
    items = []
    for row in rows:
        face, title, _ = result(row.kind, row.answers)
        items.append(MoodHistoryItem(check_date=row.check_date, kind=row.kind, level=row.level, face=face, title=title))
    return MoodHistoryOut(items=items)
