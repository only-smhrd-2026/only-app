"""돌봄 루프 (11/18 멘토링 — 모으기 → 판단 → 실행 → 반응 확인). 가족방·날짜마다 care_days 한 줄.

- 모으기·판단(plan): 그날 처음 필요할 때(첫 회상 대화·가족 홈) 전날까지의 기록으로 오늘 줄을 만든다.
  AI 를 부르지 않는다 — 평소/지켜봄/주의와 오늘 여쭐 안부 하나는 코드가 정한다(위험 판단은 코드가 한다).
- 실행(pick): 그날 첫 회상 대화의 첫 질문이 그 안부다 — 지난 이야기 질문(D77)과 같은 자리·같은 AI(story_question).
- 반응(react): 그 안부에 하신 답을 AI 가 본 신호로 적는다. 괜찮다고 하시면 그 안부는 닫고,
  여전하면 하루 쉬고 다시(CARE_ASK_MAX 번까지).
- 가족에게(journal): 무엇을 들었고, 무엇을 했고, 어떻게 답하셨는지 쉬운 문장으로. 어르신 말 원문·점수는 넣지 않는다.
'가족에게 말하지 마'라고 하신 대화의 말은 재료로 쓰지 않는다 (D55 ③).
ponytail: 안부 주제는 낱말 조각으로 고른다(TOPIC_WORDS) — 못 고르면 '마음' 안부로 물러난다.
더 정확히 하려면 새벽 AI 한 번으로.
"""

from __future__ import annotations

import re
from collections import Counter
from datetime import date, datetime, time, timedelta
from statistics import mean
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.config import (
    CARE_ASK_GAP_DAYS,
    CARE_ASK_MAX,
    CARE_BASE_DAYS,
    CARE_BASE_MIN_DAYS,
    CARE_KEEP_DAYS,
    CARE_TALK_DOWN,
    TZ,
    today_kst,
)
from app.models import ELDER_SPOKE, CareDay, Diary, MoodCheck, TalkSession

# 기운 없는 말(AI 신호 LOW)에서 안부 주제를 고르는 조각 — 띄어쓰기를 뺀 말에서 찾는다.
# '잠깐'에 걸리지 않게 '잠' 한 글자는 안 쓴다
TOPIC_WORDS = {
    "SLEEP": ("잠이", "잠을", "잠도", "잠못", "못자", "못잤", "설쳤"),
    "APPETITE": ("입맛", "밥맛", "못먹", "안먹", "먹기싫"),
    "LONELY": ("외로", "쓸쓸", "적적", "심심", "혼자"),
    "ENERGY": ("기운", "힘이없", "힘없", "귀찮", "피곤"),
}
# 마음 체크 문항 자리(0부터) → 안부 주제. 자책·집중·느려짐 문항(5~7)은 첫인사로 묻기에 무거워 쓰지 않는다
CHECK_TOPICS = {0: "INTEREST", 1: "MOOD", 2: "SLEEP", 3: "ENERGY", 4: "APPETITE"}
CHECK_ITEM_MIN = 2  # '절반 넘게 있었어요' 이상인 문항만

# 첫인사 AI(story_question)에 주는 '들은 말' 한 문장이자, 가족 돌봄 일지의 '들은 것' 문장
FACTS = {
    ("TALK", "SLEEP"): "잠을 잘 못 주무신다고 하셨어요.",
    ("TALK", "APPETITE"): "입맛이 없다고 하셨어요.",
    ("TALK", "LONELY"): "쓸쓸하실 때가 있다고 하셨어요.",
    ("TALK", "ENERGY"): "기운이 없다고 하셨어요.",
    ("TALK", "MOOD"): "마음이 좀 가라앉는다고 하셨어요.",
    ("CHECK", "SLEEP"): "마음 체크에서 잠이 편치 않은 날이 많다고 하셨어요.",
    ("CHECK", "APPETITE"): "마음 체크에서 입맛이 없는 날이 많다고 하셨어요.",
    ("CHECK", "ENERGY"): "마음 체크에서 기운이 없는 날이 많다고 하셨어요.",
    ("CHECK", "INTEREST"): "마음 체크에서 요즘 재미있는 일이 줄었다고 하셨어요.",
    ("CHECK", "MOOD"): "마음 체크에서 마음이 가라앉는 날이 많다고 하셨어요.",
    ("DIARY", "LONELY"): "일기에 쓸쓸했다고 하셨어요.",
    ("DIARY", "MOOD"): "일기에 속상한 일이 있었다고 하셨어요.",
}
ASK_NAMES = {
    "SLEEP": "잠",
    "APPETITE": "식사",
    "LONELY": "지내시는",
    "ENERGY": "기운",
    "INTEREST": "요즘 재미",
    "MOOD": "마음",
}
REACTIONS = {
    "OK": "괜찮다고 하셨어요.",
    "SAME": "아직 편치 않다고 하셨어요. 전화 한 통 드려 보세요.",
    "DENY": "그런 적 없다고 하셔서 더 여쭙지 않아요.",
}
NOTES = {
    "TALK_DOWN": "말수가 평소보다 줄었어요.",
    "QUIET": "어제는 이야기도 일기도 없었어요. 평소에는 거의 매일 하세요.",
    "SAME_AGAIN": "같은 불편이 며칠째 이어지고 있어요.",
}
# 마음 체크를 마친 어르신께 드리는 한마디 (점수·단계 이름 없이 — 가장 높게 답한 문항 하나만 받는다)
CHECK_SAY = {
    "SLEEP": "잠이 편치 않은 날이 많으셨군요. 다음에 이야기할 때 잠은 좀 주무셨는지 여쭐게요.",
    "APPETITE": "입맛이 없는 날이 많으셨군요. 다음에 이야기할 때 식사는 잘 하셨는지 여쭐게요.",
    "ENERGY": "기운이 없는 날이 많으셨군요. 다음에 이야기할 때 좀 어떠신지 여쭐게요.",
    "INTEREST": "요즘 재미있는 일이 줄었군요. 다음에는 좋아하시는 이야기를 더 나눠요.",
    "MOOD": "마음이 가라앉는 날이 많으셨군요. 다음에 이야기할 때 또 여쭐게요.",
}
CHECK_SAY_TAIL = " 말씀해 주셔서 고마워요."


def _start(day: date) -> datetime:
    return datetime.combine(day, time(0), tzinfo=TZ)


def check_topics(answers: list[int]) -> list[str]:
    """마음 체크 답 → 안부 주제. 높게 답한 문항부터(같으면 문항 순서)."""
    high = [(-answers[i], i) for i in CHECK_TOPICS if i < len(answers) and answers[i] >= CHECK_ITEM_MIN]
    return [CHECK_TOPICS[i] for _, i in sorted(high)]


def check_say(answers: list[int]) -> str | None:
    """마음 체크 끝 인사. 높게 답한 문항이 없으면 None — 화면이 평소 인사를 한다."""
    topics = check_topics(answers)
    return CHECK_SAY[topics[0]] + CHECK_SAY_TAIL if topics else None


def talk_topic(said: str) -> str:
    text = re.sub(r"\s+", "", said)
    return next((topic for topic, words in TOPIC_WORDS.items() if any(w in text for w in words)), "MOOD")


def _talk_topics(sessions: list[TalkSession]) -> list[str]:
    """기운 없는 말이 나온 대화들에서 안부 주제를 고른다. 비밀 부탁 대화는 보지 않는다."""
    topics: list[str] = []
    for session in sessions:
        if session.private_flag or session.emotion_flag == "NONE":
            continue
        marked = [
            talk_topic(str(session.turns[i - 1].get("text", "")))
            for i, turn in enumerate(session.turns)
            if i and turn.get("speaker") == "AI" and turn.get("signal") == "LOW"
        ]
        topics += marked or ["MOOD"]  # 표시가 없는 대화(위급 낱말·옛 기록)는 '마음' 안부로
    return topics


def _history(db: Session, room_id: int, today: date) -> dict[date, dict[str, Any]]:
    """오늘 전 CARE_BASE_DAYS 일의 날짜별 숫자. 기록이 없는 날도 0 으로 들어 있다."""
    first = today - timedelta(days=CARE_BASE_DAYS)
    days: dict[date, dict[str, Any]] = {
        first + timedelta(days=n): {"talks": 0, "turns": 0, "words": 0, "chips": 0, "stopped": 0, "low": False}
        for n in range(CARE_BASE_DAYS)
    }
    sessions = db.scalars(
        select(TalkSession).where(
            TalkSession.room_id == room_id,
            TalkSession.started_at >= _start(first),
            TalkSession.started_at < _start(today),
            ELDER_SPOKE,
        )
    ).all()
    for session in sessions:
        day = days[session.started_at.astimezone(TZ).date()]
        day["talks"] += 1
        day["stopped"] += session.end_reason in ("USER_STOP", "NO_RESPONSE")
        day["low"] = day["low"] or (session.emotion_flag != "NONE" and not session.private_flag)
        day.setdefault("sessions", []).append(session)
        if session.private_flag:  # 말수에는 넣지 않는다 (주간 집계와 같다, D55 ③)
            continue
        for turn in session.turns:
            if turn.get("speaker") == "ELDER":
                day["turns"] += 1
                day["words"] += len(str(turn.get("text", "")).split())
                day["chips"] += turn.get("input_type") in ("CHIP", "BUTTON")
    diaries = db.execute(
        select(Diary.posted_at, Diary.mood)
        .where(
            Diary.room_id == room_id,
            Diary.author_type == "ELDER",
            Diary.status == "POSTED",
            Diary.posted_at >= _start(first),
            Diary.posted_at < _start(today),
        )
        .order_by(Diary.posted_at)
    ).all()
    for posted_at, mood in diaries:
        days[posted_at.astimezone(TZ).date()]["diary_mood"] = mood  # 그날 마지막 일기의 기분
    return days


def _numbers(day: dict[str, Any]) -> dict[str, Any]:
    turns = day["turns"]
    return {
        "talks": day["talks"],
        "turns": turns,
        "words": day["words"],
        "avg_words": round(day["words"] / turns, 1) if turns else 0,
        "chip_ratio": round(day["chips"] / turns, 2) if turns else 0,
        "stopped": day["stopped"],
        "low": day["low"],
        "diary_mood": day.get("diary_mood"),
    }


def _signal(day: dict[str, Any]) -> set[str]:
    return ({"LOW_TALK"} if day["low"] else set()) | (
        {"DIARY_MOOD"} if day.get("diary_mood") in ("UPSET", "LONELY") else set()
    )


def _topic(db: Session, room_id: int, today: date, yday: dict[str, Any], past: list[CareDay]) -> tuple | None:
    """오늘 첫인사로 여쭐 안부 하나 → (source, topic, heard_on). 없으면 None.

    어제 새로 들은 것(말 → 일기)이 먼저, 그다음 지난번에 '여전하다'고 하신 안부, 마지막이 마음 체크 문항.
    어제 여쭌 안부는 오늘 쉬고, 같은 안부는 CARE_ASK_MAX 번까지만.
    닫힌 안부(괜찮다·그런 적 없다)는 새로 듣기 전에는 다시 묻지 않는다.
    """
    asked = Counter(p.topic for p in past if p.asked_at)
    resting = {p.topic for p in past if p.asked_at and p.care_date > today - timedelta(days=CARE_ASK_GAP_DAYS)}
    closed = {p.topic for p in past if p.reaction in ("OK", "DENY")}

    def free(topic: str) -> bool:
        return topic not in resting and asked[topic] < CARE_ASK_MAX

    heard = today - timedelta(days=1)
    for topic in _talk_topics(yday.get("sessions", [])):
        if free(topic):
            return "TALK", topic, heard
    diary_topic = {"LONELY": "LONELY", "UPSET": "MOOD"}.get(yday.get("diary_mood"))
    if diary_topic and free(diary_topic):
        return "DIARY", diary_topic, heard
    again = next((p for p in reversed(past) if p.reaction == "SAME" and p.care_date > today - timedelta(days=7)), None)
    if again and again.topic not in closed and free(again.topic):
        return again.source, again.topic, again.heard_on
    check = db.execute(
        select(MoodCheck.check_date, MoodCheck.answers)
        .where(MoodCheck.room_id == room_id, MoodCheck.check_date >= today - timedelta(days=CARE_BASE_DAYS))
        .order_by(MoodCheck.check_date.desc())
        .limit(1)
    ).first()
    if check:
        # 이 마음 체크 뒤에 이미 여쭌 주제는 다시 꺼내지 않는다 — 문항 하나에 한 번
        told = {p.topic for p in past if p.source == "CHECK" and p.asked_at and p.care_date > check.check_date}
        for topic in check_topics(check.answers):
            if topic not in told and topic not in closed and free(topic):
                return "CHECK", topic, check.check_date
    return None


def plan(db: Session, room_id: int, today: date | None = None) -> CareDay:
    """오늘 줄을 돌려준다. 없으면 전날까지의 기록으로 만든다(같은 날 두 번 불러도 한 줄)."""
    today = today or today_kst()
    row = db.scalar(select(CareDay).where(CareDay.room_id == room_id, CareDay.care_date == today))
    if row is not None:
        return row
    days = _history(db, room_id, today)
    dates = sorted(days)
    yday = days[dates[-1]]
    past = list(
        db.scalars(
            select(CareDay)
            .where(CareDay.room_id == room_id, CareDay.care_date >= dates[0], CareDay.care_date < today)
            .order_by(CareDay.care_date)
        )
    )
    picked = _topic(db, room_id, today, yday, past)
    numbers = _numbers(yday)
    reasons = sorted(_signal(yday))
    base = [days[d]["words"] / days[d]["turns"] for d in dates[:-1] if days[d]["turns"]]
    if numbers["turns"] and len(base) >= CARE_BASE_MIN_DAYS and numbers["avg_words"] < mean(base) * CARE_TALK_DOWN:
        reasons.append("TALK_DOWN")
    active = sum(1 for d in dates[-8:-1] if days[d]["talks"] or days[d].get("diary_mood"))
    if not numbers["talks"] and not numbers["diary_mood"] and active >= 5:
        reasons.append("QUIET")
    if picked and picked[0] == "CHECK":
        reasons.append("CHECK_ITEM")
    same = sum(1 for p in past if p.reaction == "SAME" and p.care_date > today - timedelta(days=7))
    if same >= 2:
        reasons.append("SAME_AGAIN")
    signal_days = sum(1 for d in dates[-3:] if _signal(days[d]))  # 최근 3일 가운데 마음이 가라앉은 날
    level = "CARE" if signal_days >= 2 or same >= 2 else "WATCH" if reasons or picked else "USUAL"
    source, topic, heard_on = picked or (None, None, None)
    db.execute(
        pg_insert(CareDay)
        .values(
            room_id=room_id,
            care_date=today,
            numbers=numbers,
            level=level,
            reasons=reasons,
            source=source,
            topic=topic,
            heard_on=heard_on,
        )
        .on_conflict_do_nothing(constraint="uq_care_days_room_id_care_date")
    )
    db.execute(delete(CareDay).where(CareDay.care_date < today - timedelta(days=CARE_KEEP_DAYS)))
    db.flush()
    return db.scalar(select(CareDay).where(CareDay.room_id == room_id, CareDay.care_date == today))


def pick(db: Session, room_id: int) -> CareDay | None:
    """오늘 첫 회상 대화에서 여쭐 안부. 없거나 이미 여쭸으면 None."""
    row = plan(db, room_id)
    return row if row.topic and row.asked_at is None else None


def fact(row: CareDay) -> str:
    return FACTS[(row.source, row.topic)]


def react(db: Session, room_id: int, signal: str) -> None:
    """오늘의 안부에 하신 답 — AI 가 그 말에서 본 신호를 반응으로 적는다. 그만하자는 말(STOP)은 답으로 치지 않는다."""
    row = db.scalar(select(CareDay).where(CareDay.room_id == room_id, CareDay.care_date == today_kst()))
    if row is None or row.asked_at is None or row.reaction is not None or signal == "STOP":
        return
    row.reaction = "DENY" if signal == "DENY" else "OK" if signal == "NONE" else "SAME"


def journal(db: Session, room_id: int, days: int = 7) -> list[dict[str, Any]]:
    """가족 홈 돌봄 일지 — 최근 며칠 가운데 살핀 것이 있는 날만, 새 날부터. 문장은 여기서 만든다."""
    today = today_kst()
    plan(db, room_id, today)
    rows = db.scalars(
        select(CareDay)
        .where(
            CareDay.room_id == room_id,
            CareDay.care_date > today - timedelta(days=days),
            CareDay.care_date <= today,
            CareDay.level != "USUAL",
        )
        .order_by(CareDay.care_date.desc())
    ).all()
    out = []
    for row in rows:
        did = None
        if row.topic:
            name = ASK_NAMES[row.topic]
            if row.asked_at:
                did = f"첫인사로 {name} 안부를 여쭸어요."
            elif row.care_date == today:
                did = f"오늘 첫인사로 {name} 안부를 여쭐게요."
            else:
                did = "그날은 이야기를 안 하셔서 여쭙지 못했어요."
        out.append(
            {
                "date": row.care_date,
                "level": row.level,
                "heard": FACTS[(row.source, row.topic)] if row.topic else None,
                "did": did,
                "reaction": REACTIONS.get(row.reaction),
                "notes": [NOTES[r] for r in row.reasons if r in NOTES],
            }
        )
    return out
