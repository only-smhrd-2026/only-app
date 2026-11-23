"""주간 이야기 숫자·목록 집계 (D19). AI 요약과 게시는 후속 작업이다.

알림은 예약 작업이 AI 요약 뒤에 보낸다.
'이번 주 달라진 점'(changes)은 저장하지 않고 조회할 때 앞 주들과 견줘 만든다.
"""

from collections import Counter
from datetime import date, datetime, time, timedelta
from statistics import mean

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.config import (
    TZ,
    WEEKLY_BASE_MIN_WEEKS,
    WEEKLY_BASE_WEEKS,
    WEEKLY_DAYS_GAP,
    WEEKLY_HOUR,
    WEEKLY_MOOD_LOW_DAYS,
    WEEKLY_TALK_LONG,
    WEEKLY_TALK_SHORT,
)
from app.models import ELDER_SPOKE, CareDay, Diary, MoodCheck, Notification, TalkSession, UrgentAlert, WeeklySummary
from app.routers.diaries import _member_names
from app.services.care import ASK_NAMES

# '이번 주 달라진 점'의 문장 조각 (changes). 점수·진단처럼 들리는 말은 쓰지 않는다 (NFR-DE-003)
# 마음 체크 단계 문장 — 가족 홈(HOME_001.tsx 의 CHECK_TEXT)과 글자가 같다 (D56)
CHECK_TEXT = {
    "USUAL": "평소와 비슷해요",
    "DOWN": "조금 가라앉으신 편이에요",
    "HARD": "많이 힘드신 것 같아요 · 전문 상담을 권해 드려요",
}
CHECK_WAS = {"USUAL": "평소와 비슷했어요", "DOWN": "조금 가라앉으신 편이었어요", "HARD": "많이 힘드신 것 같았어요"}
CARE_SAID = {"OK": "괜찮다고", "SAME": "아직 편치 않다고", "DENY": "그런 적 없다고"}  # 오늘의 안부에 하신 답
# 가족에게 간 알림 (notifications.kind → 문장). 위급 알림은 urgent_alerts 로 따로 센다
NOTICE_TEXT = {
    "MOOD_LOW_2D": "'안부 전화 어떠세요?' 알림이 {n}번 갔어요.",  # 알림 제목 (routers/mood.LOW_DAYS_TITLE, 11/23)
    "NO_RECORD_2D": "이틀 동안 기록이 없어 알림이 {n}번 갔어요.",
}


def window(now: datetime) -> tuple[datetime, datetime, date]:
    """지금까지 끝난 가장 최근 일요일 저녁 집계 창과 그 주 월요일을 돌려준다."""
    now = now.astimezone(TZ)
    days = (now.weekday() + 1) % 7
    end = (now - timedelta(days=days)).replace(hour=WEEKLY_HOUR, minute=0, second=0, microsecond=0)
    if end > now:
        end -= timedelta(days=7)
    return end - timedelta(days=7), end, (end - timedelta(days=6)).date()


def build(db: Session, room_id: int, now: datetime) -> bool:
    """가족방 집계를 한 번 저장하며 같은 주를 다시 계산해도 처음 결과를 유지한다."""
    start, end, week_start = window(now)
    sessions = db.scalars(
        select(TalkSession).where(
            TalkSession.room_id == room_id, TalkSession.started_at >= start, TalkSession.started_at < end, ELDER_SPOKE
        )
    ).all()
    diaries = db.scalars(
        select(Diary)
        .where(
            Diary.room_id == room_id,
            Diary.author_type == "ELDER",
            Diary.status == "POSTED",
            Diary.posted_at >= start,
            Diary.posted_at < end,
        )
        .order_by(Diary.posted_at, Diary.diary_id)
    ).all()
    memory_dates = {s.started_at.astimezone(TZ).date() for s in sessions if s.kind in ("MEMORY", "ALBUM")}
    moods = {d.posted_at.astimezone(TZ).date(): d.mood for d in diaries}
    words = turns = 0
    for session in sessions:
        if session.private_flag:  # '가족에게 말하지 마'라고 하신 대화는 이야기한 날로만 세고 말 수에서는 뺀다 (D55 ③)
            continue
        for turn in session.turns:
            if turn.get("speaker") == "ELDER":  # 키가 빠진 칸 하나 때문에 그 방 집계 전체가 실패하지 않게
                turns += 1
                words += len(turn.get("text", "").split())
    mood_trend = [
        {"date": (day := week_start + timedelta(days=offset)).isoformat(), "mood": moods.get(day)}
        for offset in range(7)
    ]
    stmt = (
        pg_insert(WeeklySummary)
        .values(
            room_id=room_id,
            week_start=week_start,
            memory_days=min(len(memory_dates), 7),
            diary_days=min(len(moods), 7),
            qa_list=[],
            recall_check={},
            mood_trend=mood_trend,
            talk_volume={"words": words, "turns": turns, "avg_words": round(words / turns, 1) if turns else 0},
            diaries=[
                {"diary_id": d.diary_id, "date": d.posted_at.astimezone(TZ).date().isoformat(), "mood": d.mood}
                for d in diaries
            ],
            rule_check_passed=False,
            model_version="none",
        )
        .on_conflict_do_nothing(constraint="uq_weekly_summaries_room_id_week_start")
        .returning(WeeklySummary.summary_id)
    )
    created = db.execute(stmt).scalar_one_or_none()
    db.commit()
    return created is not None and bool(sessions or diaries)


def _line(kind: str, text: str, watch: bool = False) -> dict[str, str]:
    return {"kind": kind, "text": text, "tone": "watch" if watch else "calm"}


def _md(day: date) -> str:
    return f"{day.month}월 {day.day}일"


def _low_days(row: WeeklySummary) -> int:
    """일기 기분으로 속상했어요·쓸쓸했어요를 고르신 날 수."""
    return sum(day.get("mood") in ("UPSET", "LONELY") for day in row.mood_trend)


def changes(db: Session, row: WeeklySummary) -> list[dict[str, str]]:
    """'이번 주 달라진 점' — 그 주를 바로 앞 주들과 견준 변화와 그 주 알림 이력 (11/18 멘토링).

    저장하지 않고 읽을 때 계산한다 — 지난 주를 볼 때도 그 주 기준이다. 한 줄 = {kind, text, tone},
    tone 은 calm(평소) | watch(살펴볼 것). 견줄 자료가 모자란 줄은 만들지 않는다.
    문장은 여기서 만든다 — 어르신이 하신 말·일기 글·점수는 넣지 않는다 (NFR-DE-003).
    """
    room_id, week = row.room_id, row.week_start
    end = datetime.combine(week + timedelta(days=6), time(WEEKLY_HOUR), tzinfo=TZ)  # 집계 창과 같다 (D19)
    start = end - timedelta(days=7)
    past = db.scalars(
        select(WeeklySummary)
        .where(
            WeeklySummary.room_id == room_id,
            WeeklySummary.week_start >= week - timedelta(weeks=WEEKLY_BASE_WEEKS),
            WeeklySummary.week_start < week,
        )
        .order_by(WeeklySummary.week_start)
    ).all()
    out: list[dict[str, str]] = []

    # ① 이야기한 날 — 앞 주들의 평균과
    if len(past) >= WEEKLY_BASE_MIN_WEEKS:
        days, usual = row.memory_days, mean(p.memory_days for p in past)
        if abs(days - usual) < WEEKLY_DAYS_GAP:
            out.append(_line("TALK_DAYS", f"이야기한 날은 평소와 비슷했어요({days}일)."))
        else:
            less = days < usual
            moved = "줄어" if less else "늘어"
            text = f"이야기한 날이 평소({int(usual + 0.5)}일쯤)보다 {moved} {days}일이었어요."
            out.append(_line("TALK_DAYS", text, less))

    # ② 한마디 길이 — 말이 있던 주끼리만
    lengths = [p.talk_volume["avg_words"] for p in past if p.talk_volume["turns"]]
    if row.talk_volume["turns"] and len(lengths) >= WEEKLY_BASE_MIN_WEEKS:
        length, usual = row.talk_volume["avg_words"], mean(lengths)
        if length < usual * WEEKLY_TALK_SHORT:
            out.append(_line("TALK_LENGTH", "한 번에 하시는 말이 평소보다 짧아졌어요.", True))
        elif length > usual * WEEKLY_TALK_LONG:
            out.append(_line("TALK_LENGTH", "한 번에 하시는 말이 평소보다 길어졌어요."))

    # ③ 기분 — 바로 앞 주(줄이 있을 때만)와
    low = _low_days(row)
    was = _low_days(past[-1]) if past and past[-1].week_start == week - timedelta(days=7) else None
    if low >= WEEKLY_MOOD_LOW_DAYS or (was is not None and low > was):
        tail = "" if was is None else f"(지난주 {was}일)"
        out.append(_line("MOOD", f"속상하거나 쓸쓸했다고 하신 날이 {low}일 있었어요{tail}.", True))
    elif not low and (was or 0) >= WEEKLY_MOOD_LOW_DAYS and any(day.get("mood") for day in row.mood_trend):
        # 일기가 한 편도 없던 주는 기분을 모른다 — '편안해 보인다'고 하지 않는다
        out.append(_line("MOOD", "지난주보다 기분이 편안해 보이세요."))

    # ④ 마음 체크 — 그 주(월~일)에 하신 것과 그 앞의 것
    checks = db.execute(
        select(MoodCheck.check_date, MoodCheck.level)
        .where(
            MoodCheck.room_id == room_id,
            MoodCheck.kind.in_(("PHQ8", "PHQ9")),  # 가족에게는 마음 체크(PHQ)만 보인다 (11/23)
            MoodCheck.check_date <= week + timedelta(days=6),
        )
        .order_by(MoodCheck.check_date.desc())
        .limit(2)
    ).all()
    if checks and checks[0].check_date >= week:
        check, *before = checks
        text = f"{_md(check.check_date)} 마음 체크에서는 {CHECK_TEXT[check.level]}."
        if before and before[0].level != check.level:
            text += f" 지난번({_md(before[0].check_date)})에는 {CHECK_WAS[before[0].level]}."
        out.append(_line("CHECK", text, check.level != "USUAL"))

    # ⑤ 꼬마심심이가 한 일 — 첫인사로 여쭌 안부와 하신 답 (돌봄 루프, services/care.py)
    asked = db.execute(
        select(CareDay.topic, CareDay.reaction)
        .where(CareDay.room_id == room_id, CareDay.asked_at >= start, CareDay.asked_at < end)
        .order_by(CareDay.care_date)
    ).all()
    if asked:
        got = Counter(a.reaction for a in asked)

        def times(n: int) -> str:  # '1번은' — 한 번만 여쭸으면 빼고, 모두 같은 답이면 '모두'
            return "" if len(asked) == 1 else "모두 " if n == len(asked) else f"{n}번은 "

        said = ", ".join(times(got[r]) + word for r, word in CARE_SAID.items() if got[r])
        topics = "·".join(dict.fromkeys(ASK_NAMES[a.topic] for a in asked))
        tail = f"고, {said} 하셨어요." if said else "어요."
        out.append(_line("CARE", f"꼬마심심이가 {topics} 안부를 {len(asked)}번 여쭸{tail}", got["SAME"] > 0))

    # ⑥ 알림 이력 — 급한 알림과 [제가 연락했어요], 가족에게 간 알림
    urgent = db.execute(
        select(UrgentAlert.acked_by, UrgentAlert.acked_at)
        .where(UrgentAlert.room_id == room_id, UrgentAlert.created_at >= start, UrgentAlert.created_at < end)
        .order_by(UrgentAlert.alert_id)
    ).all()
    if urgent:
        head = f"급한 알림이 {len(urgent)}번 있었고"
        waiting = sum(a.acked_at is None for a in urgent)
        if waiting:
            some = f"{waiting}번은 " if waiting < len(urgent) else ""
            out.append(_line("ALERT", f"{head} {some}아직 연락했다는 표시가 없어요.", True))
        else:
            names = _member_names(db, room_id)
            who = "·".join(dict.fromkeys(f"{names.get(a.acked_by, '가족')}님" for a in urgent))
            out.append(_line("ALERT", f"{head} {who}이 연락했어요."))
    # 알림은 가족 한 사람마다 한 줄이라, 같은 때 보낸 묶음(sent_at 이 같다)을 방 기준 한 번으로 센다
    sent = dict(
        db.execute(
            select(Notification.kind, func.count(func.distinct(Notification.sent_at)))
            .where(
                Notification.room_id == room_id,
                Notification.kind.in_(list(NOTICE_TEXT)),
                Notification.sent_at >= start,
                Notification.sent_at < end,
            )
            .group_by(Notification.kind)
        ).all()
    )
    out += [_line("ALERT", text.format(n=sent[kind])) for kind, text in NOTICE_TEXT.items() if kind in sent]
    return out
