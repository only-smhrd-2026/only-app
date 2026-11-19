"""주간 이야기 '이번 주 달라진 점' (11/18 멘토링): 그 주를 앞 주들과 견준 변화와 그 주 알림 이력 문장.

조회할 때 계산한다(services/weekly.changes). 자료가 모자란 줄은 없고, 문장에는 금지어·어르신 말이 없다.
"""

from datetime import date, datetime, time, timedelta

import pytest
from sqlalchemy import func, select

from app.ai.schemas import BANNED_WORDS
from app.config import ROOT, TZ, now_kst
from app.db import SessionLocal
from app.models import CareDay, MoodCheck, Notification, UrgentAlert, WeeklySummary
from app.routers.devices import notify_family
from app.services import alerts, weekly
from tests.conftest import make_room, signup
from tests.test_room_members import join
from tests.test_weekly import _talk

WEEK = date(2026, 11, 9)  # 보는 주의 월요일 — 집계 창은 11/8(일) 19시 ~ 11/15(일) 19시
NOW = datetime(2026, 11, 15, 19, tzinfo=TZ)
NEVER = [*BANNED_WORDS, "등수", "기억력"]  # 가족에게 보이는 문장에 없어야 하는 말 (NFR-DE-003)
U, L, G = "UPSET", "LONELY", "GOOD"


def _at(day, hour=10):
    return datetime(2026, 11, day, hour, tzinfo=TZ)


def _room(client) -> int:
    signup(client)
    return make_room(client)["room_id"]


def _week(room_id, weeks_ago=0, days=0, avg=0.0, moods=()):
    """그 주 줄을 바로 넣는다. avg = 한마디 길이(0 이면 말이 없던 주), moods = 월요일부터의 일기 기분."""
    start = WEEK - timedelta(weeks=weeks_ago)
    trend = [
        {"date": (start + timedelta(days=n)).isoformat(), "mood": moods[n] if n < len(moods) else None}
        for n in range(7)
    ]
    with SessionLocal() as db:
        db.add(
            WeeklySummary(
                room_id=room_id,
                week_start=start,
                memory_days=days,
                diary_days=len(moods),
                qa_list=[],
                recall_check={},
                mood_trend=trend,
                talk_volume={"words": round(avg * 10), "turns": 10 if avg else 0, "avg_words": avg},
                diaries=[],
                rule_check_passed=False,
                model_version="none",
            )
        )
        db.commit()


def _changes(client, room_id, week=None) -> list[tuple[str, str, str]]:
    """그 주(안 주면 가장 최근 주)의 달라진 점 → (kind, tone, text). 지나가는 문장마다 금지어도 본다."""
    response = client.get(f"/api/rooms/{room_id}/weekly", params={"week_start": week} if week else None)
    assert response.status_code == 200, response.text
    lines = response.json()["changes"]
    for line in lines:
        assert set(line) == {"kind", "text", "tone"}
        assert not [word for word in NEVER if word in line["text"]], line["text"]
    return [(line["kind"], line["tone"], line["text"]) for line in lines]


def test_no_line_until_two_earlier_weeks(client):
    """견줄 앞 주가 2개가 안 되면 이야기한 날·한마디 길이 줄을 만들지 않는다 — 억지로 채우지 않는다."""
    room_id = _room(client)
    _week(room_id, days=1, avg=2.0)
    assert _changes(client, room_id) == []
    _week(room_id, 1, days=6, avg=9.0)
    assert _changes(client, room_id) == []
    _week(room_id, 2, days=6, avg=9.0)
    assert _changes(client, room_id) == [
        ("TALK_DAYS", "watch", "이야기한 날이 평소(6일쯤)보다 줄어 1일이었어요."),
        ("TALK_LENGTH", "watch", "한 번에 하시는 말이 평소보다 짧아졌어요."),
    ]


@pytest.mark.parametrize(
    "earlier,days,tone,text",
    [
        ([5, 5], 3, "watch", "이야기한 날이 평소(5일쯤)보다 줄어 3일이었어요."),
        ([5, 5], 4, "calm", "이야기한 날은 평소와 비슷했어요(4일)."),
        ([4, 4], 5, "calm", "이야기한 날은 평소와 비슷했어요(5일)."),
        ([4, 4], 6, "calm", "이야기한 날이 평소(4일쯤)보다 늘어 6일이었어요."),
        ([4, 5], 3, "calm", "이야기한 날은 평소와 비슷했어요(3일)."),  # 평균 4.5일 — 1.5일 차이는 비슷
        ([4, 5], 2, "watch", "이야기한 날이 평소(5일쯤)보다 줄어 2일이었어요."),
        ([0, 5, 5, 5, 5], 3, "watch", "이야기한 날이 평소(5일쯤)보다 줄어 3일이었어요."),  # 5주 전은 보지 않는다
    ],
)
def test_talk_days_against_the_last_four_weeks(client, earlier, days, tone, text):
    room_id = _room(client)
    for weeks_ago, n in enumerate(reversed(earlier), 1):
        _week(room_id, weeks_ago, days=n)
    _week(room_id, days=days)
    assert _changes(client, room_id) == [("TALK_DAYS", tone, text)]


@pytest.mark.parametrize(
    "avg,line",
    [
        (6.9, [("TALK_LENGTH", "watch", "한 번에 하시는 말이 평소보다 짧아졌어요.")]),
        (7.0, []),  # 평소(10어절)의 0.7 배 '미만'만
        (13.0, []),  # 1.3 배 '초과'만
        (13.1, [("TALK_LENGTH", "calm", "한 번에 하시는 말이 평소보다 길어졌어요.")]),
        (0.0, []),  # 그 주에 말이 없었으면 견주지 않는다 (이야기한 날 줄이 알린다)
    ],
)
def test_talk_length_edges(client, avg, line):
    room_id = _room(client)
    _week(room_id, 1, days=5, avg=10.0)
    _week(room_id, 2, days=5, avg=10.0)
    _week(room_id, days=5, avg=avg)
    assert _changes(client, room_id) == [("TALK_DAYS", "calm", "이야기한 날은 평소와 비슷했어요(5일)."), *line]


def test_talk_length_needs_two_weeks_with_talk(client):
    """말이 없던 주는 평소에서 뺀다 — 말이 있던 주가 2개가 돼야 견준다."""
    room_id = _room(client)
    _week(room_id, 1, avg=10.0)
    _week(room_id, 2)  # 말이 없던 주
    _week(room_id, avg=2.0)
    assert [kind for kind, *_ in _changes(client, room_id)] == ["TALK_DAYS"]
    _week(room_id, 3, avg=10.0)
    assert [kind for kind, *_ in _changes(client, room_id)] == ["TALK_DAYS", "TALK_LENGTH"]


@pytest.mark.parametrize(
    "last,this,line",
    [
        ([U], [U, L, U], ("watch", "속상하거나 쓸쓸했다고 하신 날이 3일 있었어요(지난주 1일).")),
        ([G], [L], ("watch", "속상하거나 쓸쓸했다고 하신 날이 1일 있었어요(지난주 0일).")),  # 지난주보다 늘었다
        (None, [U, G, L], ("watch", "속상하거나 쓸쓸했다고 하신 날이 2일 있었어요.")),  # 지난주 줄이 없으면 날 수만
        (None, [U], None),  # 1일이고 견줄 지난주가 없다
        ([U], [L], None),  # 1일로 같다
        ([U, U, L], [U], None),  # 줄었지만 0일은 아니다
        ([U, L], [G], ("calm", "지난주보다 기분이 편안해 보이세요.")),
        ([U, L], [], None),  # 일기가 없던 주는 기분을 모른다
    ],
)
def test_mood_days(client, last, this, line):
    room_id = _room(client)
    if last is not None:
        _week(room_id, 1, moods=last)
    _week(room_id, moods=this)
    assert _changes(client, room_id) == ([("MOOD", *line)] if line else [])


def _check(room_id, day, level):
    with SessionLocal() as db:
        db.add(MoodCheck(room_id=room_id, check_date=day, answers=[0] * 8, total=0, level=level))
        db.commit()


@pytest.mark.parametrize(
    "level,before,tone,text",
    [
        ("USUAL", None, "calm", "11월 12일 마음 체크에서는 평소와 비슷해요."),
        (
            "DOWN",
            "DOWN",
            "watch",
            "11월 12일 마음 체크에서는 조금 가라앉으신 편이에요.",
        ),  # 지난번과 같으면 덧붙이지 않는다
        (
            "DOWN",
            "USUAL",
            "watch",
            "11월 12일 마음 체크에서는 조금 가라앉으신 편이에요. 지난번(10월 29일)에는 평소와 비슷했어요.",
        ),
        (
            "HARD",
            "DOWN",
            "watch",
            "11월 12일 마음 체크에서는 많이 힘드신 것 같아요 · 전문 상담을 권해 드려요."
            " 지난번(10월 29일)에는 조금 가라앉으신 편이었어요.",
        ),
        (
            "USUAL",
            "HARD",
            "calm",
            "11월 12일 마음 체크에서는 평소와 비슷해요. 지난번(10월 29일)에는 많이 힘드신 것 같았어요.",
        ),
    ],
)
def test_mood_check_level_and_last_time(client, level, before, tone, text):
    room_id = _room(client)
    _week(room_id)
    if before:
        _check(room_id, date(2026, 10, 29), before)
    _check(room_id, date(2026, 11, 12), level)
    assert _changes(client, room_id) == [("CHECK", tone, text)]


def test_mood_check_only_inside_the_week(client):
    """그 주(월~일)에 한 마음 체크만 — 앞 주·다음 주 것은 그 주 줄이 되지 않는다."""
    room_id = _room(client)
    _week(room_id)
    _check(room_id, date(2026, 11, 8), "HARD")
    _check(room_id, date(2026, 11, 16), "HARD")
    assert _changes(client, room_id) == []
    _check(room_id, date(2026, 11, 15), "USUAL")  # 일요일 밤에 해도 그 주
    assert _changes(client, room_id) == [
        ("CHECK", "calm", "11월 15일 마음 체크에서는 평소와 비슷해요. 지난번(11월 8일)에는 많이 힘드신 것 같았어요.")
    ]


def test_check_sentences_are_the_family_home_ones():
    """마음 체크 단계 문장은 가족 홈(HOME_001 의 CHECK_TEXT)과 글자가 같다."""
    home = (ROOT / "frontend/src/screens/family/HOME_001.tsx").read_text("utf-8")
    for level, text in weekly.CHECK_TEXT.items():
        assert f"{level}: '{text}'" in home


def _care(room_id, asked_at, topic="SLEEP", reaction=None, asked=True):
    with SessionLocal() as db:
        db.add(
            CareDay(
                room_id=room_id,
                care_date=asked_at.date(),
                level="WATCH",
                source="TALK",
                topic=topic,
                asked_at=asked_at if asked else None,
                reaction=reaction,
            )
        )
        db.commit()


@pytest.mark.parametrize(
    "asks,tone,text",
    [
        ([("SLEEP", None)], "calm", "꼬마심심이가 잠 안부를 1번 여쭸어요."),
        ([("SLEEP", "OK")], "calm", "꼬마심심이가 잠 안부를 1번 여쭸고, 괜찮다고 하셨어요."),
        ([("MOOD", "DENY")], "calm", "꼬마심심이가 마음 안부를 1번 여쭸고, 그런 적 없다고 하셨어요."),
        (
            [("SLEEP", "OK"), ("APPETITE", None)],
            "calm",
            "꼬마심심이가 잠·식사 안부를 2번 여쭸고, 1번은 괜찮다고 하셨어요.",
        ),
        ([("SLEEP", "OK"), ("SLEEP", "OK")], "calm", "꼬마심심이가 잠 안부를 2번 여쭸고, 모두 괜찮다고 하셨어요."),
        (
            [("SLEEP", "OK"), ("APPETITE", "SAME")],
            "watch",
            "꼬마심심이가 잠·식사 안부를 2번 여쭸고, 1번은 괜찮다고, 1번은 아직 편치 않다고 하셨어요.",
        ),
    ],
)
def test_care_asks_and_answers(client, asks, tone, text):
    room_id = _room(client)
    _week(room_id)
    for n, (topic, reaction) in enumerate(asks):
        _care(room_id, _at(10 + 2 * n), topic, reaction)
    assert _changes(client, room_id) == [("CARE", tone, text)]


def test_care_only_asked_days_inside_the_window(client):
    room_id = _room(client)
    _week(room_id)
    _care(room_id, _at(8, 18), reaction="SAME")  # 창이 열리기 전 — 앞 주 것
    _care(room_id, _at(10), asked=False)  # 이야기를 안 하셔서 여쭙지 못한 날
    _care(room_id, _at(15, 20), reaction="SAME")  # 창이 닫힌 뒤 — 다음 주 것
    assert _changes(client, room_id) == []


def test_urgent_alert_and_who_called(client):
    me = signup(client)
    room_id = make_room(client)["room_id"]
    _week(room_id)
    with SessionLocal() as db:
        db.add(UrgentAlert(room_id=room_id, kind="MOOD", created_at=_at(8, 18)))  # 창 밖
        first = UrgentAlert(room_id=room_id, kind="BODY", created_at=_at(8, 19))  # 창이 열리는 시각부터
        db.add(first)
        db.flush()  # 번호가 다음 알림보다 앞서게
        second = UrgentAlert(room_id=room_id, kind="MOOD", created_at=_at(12))
        db.add(second)
        db.add(UrgentAlert(room_id=room_id, kind="BODY", created_at=NOW))  # 창이 닫힌 시각 — 다음 주 것
        db.commit()
        first_id, second_id = first.alert_id, second.alert_id
    assert _changes(client, room_id) == [("ALERT", "watch", "급한 알림이 2번 있었고 아직 연락했다는 표시가 없어요.")]
    with SessionLocal() as db:
        alerts.ack(db, room_id, first_id, me["user_id"])  # 첫 알림까지만 닫힌다
    assert _changes(client, room_id) == [
        ("ALERT", "watch", "급한 알림이 2번 있었고 1번은 아직 연락했다는 표시가 없어요.")
    ]
    assert client.post(f"/api/rooms/{room_id}/alerts/{second_id}/ack").status_code == 200
    assert _changes(client, room_id) == [("ALERT", "calm", "급한 알림이 2번 있었고 테스터님이 연락했어요.")]


def test_notices_count_once_per_room_however_many_family(client):
    """알림은 가족 한 사람마다 한 줄씩 생긴다 — 같은 때 보낸 묶음은 방 기준 한 번으로 센다."""
    room_id = _room(client)
    join(client, room_id)  # 가족이 두 사람
    kinds = ("MOOD_LOW_2D", "NO_RECORD_2D", "NO_RECORD_2D")
    with SessionLocal() as db:
        weekly.build(db, room_id, now_kst() + timedelta(days=7))  # 지금이 들어 있는 주를 닫힌 주로
        for kind in kinds:
            notify_family(db, room_id, kind, "알림 제목")
            db.commit()
        mine = Notification.room_id == room_id, Notification.kind.in_(kinds)
        assert db.scalar(select(func.count()).select_from(Notification).where(*mine)) == 6
    assert _changes(client, room_id) == [
        ("ALERT", "calm", "'전화 한 통 드려 보세요' 알림이 1번 갔어요."),
        ("ALERT", "calm", "이틀 동안 기록이 없어 알림이 2번 갔어요."),
    ]


def test_earlier_week_is_compared_with_its_own_past(client):
    """지난 주를 week_start 로 보면 그 주 기준 — 그 뒤 주의 숫자·마음 체크·알림이 섞이지 않는다."""
    room_id = _room(client)
    for weeks_ago, days in enumerate([1, 3, 6, 6]):  # 이번 주 1일 ← 3일 ← 6일 ← 6일
        _week(room_id, weeks_ago, days=days)
    _check(room_id, date(2026, 11, 4), "DOWN")
    _care(room_id, _at(5), reaction="OK")
    with SessionLocal() as db:
        db.add(UrgentAlert(room_id=room_id, kind="BODY", created_at=_at(12)))
        db.commit()
    assert _changes(client, room_id) == [
        ("TALK_DAYS", "watch", "이야기한 날이 평소(5일쯤)보다 줄어 1일이었어요."),
        ("ALERT", "watch", "급한 알림이 1번 있었고 아직 연락했다는 표시가 없어요."),
    ]
    assert _changes(client, room_id, "2026-11-02") == [
        ("TALK_DAYS", "watch", "이야기한 날이 평소(6일쯤)보다 줄어 3일이었어요."),
        ("CHECK", "watch", "11월 4일 마음 체크에서는 조금 가라앉으신 편이에요."),
        ("CARE", "calm", "꼬마심심이가 잠 안부를 1번 여쭸고, 괜찮다고 하셨어요."),
    ]
    assert _changes(client, room_id, "2026-10-26") == []  # 앞 주가 하나뿐이다


def test_weeks_built_from_real_talks(client):
    """집계(build)가 만든 주 줄 그대로: 닷새씩 길게 이야기하시다가 이번 주는 이틀·짧게."""
    room_id = _room(client)
    plan = ((2, 5, "마당에서 김장하던 날이 생각나요"), (1, 5, "마당에서 김장하던 날이 생각나요"), (0, 2, "네"))
    with SessionLocal() as db:
        for weeks_ago, days, said in plan:
            monday = datetime.combine(WEEK - timedelta(weeks=weeks_ago), time(10), tzinfo=TZ)
            for n in range(days):
                _talk(db, room_id, monday + timedelta(days=n), texts=(said,))
        db.commit()
        for weeks_ago, *_ in plan:
            weekly.build(db, room_id, NOW - timedelta(weeks=weeks_ago))
    assert _changes(client, room_id) == [
        ("TALK_DAYS", "watch", "이야기한 날이 평소(5일쯤)보다 줄어 2일이었어요."),
        ("TALK_LENGTH", "watch", "한 번에 하시는 말이 평소보다 짧아졌어요."),
    ]


def test_all_lines_in_order_without_banned_words(client):
    """여섯 가지가 다 있는 주 — 줄 순서와, 어느 문장에도 금지어가 없는 것 (NFR-DE-003)."""
    me = signup(client)
    room_id = make_room(client)["room_id"]
    _week(room_id, 2, days=5, avg=10.0)
    _week(room_id, 1, days=5, avg=10.0, moods=[G, U, L])
    _week(room_id, days=7, avg=14.0, moods=[G])
    _check(room_id, date(2026, 11, 12), "HARD")
    _care(room_id, _at(10), "LONELY", "DENY")
    _care(room_id, _at(12), "INTEREST", "SAME")
    _care(room_id, _at(14), "ENERGY", "OK")
    with SessionLocal() as db:
        alert = UrgentAlert(room_id=room_id, kind="MOOD", created_at=_at(13))
        db.add(alert)
        db.flush()
        for kind, day in (("MOOD_LOW_2D", 11), ("NO_RECORD_2D", 9), ("NO_RECORD_2D", 10)):
            db.add(Notification(room_id=room_id, target_type="FAMILY", kind=kind, title="알림 제목", sent_at=_at(day)))
        alerts.ack(db, room_id, alert.alert_id, me["user_id"])
    lines = _changes(client, room_id)
    assert lines == [
        ("TALK_DAYS", "calm", "이야기한 날이 평소(5일쯤)보다 늘어 7일이었어요."),
        ("TALK_LENGTH", "calm", "한 번에 하시는 말이 평소보다 길어졌어요."),
        ("MOOD", "calm", "지난주보다 기분이 편안해 보이세요."),
        ("CHECK", "watch", "11월 12일 마음 체크에서는 많이 힘드신 것 같아요 · 전문 상담을 권해 드려요."),
        (
            "CARE",
            "watch",
            "꼬마심심이가 지내시는·요즘 재미·기운 안부를 3번 여쭸고,"
            " 1번은 괜찮다고, 1번은 아직 편치 않다고, 1번은 그런 적 없다고 하셨어요.",
        ),
        ("ALERT", "calm", "급한 알림이 1번 있었고 테스터님이 연락했어요."),
        ("ALERT", "calm", "'전화 한 통 드려 보세요' 알림이 1번 갔어요."),
        ("ALERT", "calm", "이틀 동안 기록이 없어 알림이 2번 갔어요."),
    ]
    assert not [(word, text) for *_, text in lines for word in NEVER if word in text]
