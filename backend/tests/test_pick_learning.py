"""오늘의 한 장 고르기에 어르신 반응을 반영한다 (11/19 돌봄 루프): 슬퍼하신 사진은 쉬고, 길게 이야기하신 주제는 더,
넘기신 주제는 덜."""

import uuid
from datetime import datetime, time, timedelta

from app.config import TZ, now_kst, today_kst
from app.db import SessionLocal
from app.models import DailyPick, Photo, TalkSession
from app.services import picks
from tests.conftest import add_photos, make_room, signup


def _room(client, tags) -> tuple[int, list[int]]:
    """사진마다 가족이 고른 활동(tags)을 붙인 가족방."""
    signup(client)
    room_id = make_room(client)["room_id"]
    photo_ids = add_photos(room_id, len(tags))
    with SessionLocal() as db:
        for photo_id, tag in zip(photo_ids, tags, strict=True):
            db.get(Photo, photo_id).corrected_activity = tag
        db.commit()
    return room_id, photo_ids


def _talk(room_id, photo_id, words, *, days_ago=20, flag="NONE", sad=False) -> None:
    turns = [
        {"turn_no": 1, "speaker": "AI", "text": "이 사진 보니 어떠세요?"},
        {"turn_no": 2, "speaker": "ELDER", "text": " ".join(["말"] * words), "reply_to_turn_no": 1},
        {"turn_no": 3, "speaker": "AI", "text": "그러셨군요."} | ({"signal": "SAD"} if sad else {}),
    ]
    with SessionLocal() as db:
        db.add(
            TalkSession(
                session_id=uuid.uuid4(),
                room_id=room_id,
                kind="MEMORY",
                photo_id=photo_id,
                input_mode="VOICE",
                started_at=datetime.combine(today_kst() - timedelta(days=days_ago), time(10), tzinfo=TZ),
                emotion_flag=flag,
                turns=turns,
            )
        )
        db.commit()


def _pool(room_id, candidates) -> list[int]:
    with SessionLocal() as db:
        return picks._pool(db, room_id, candidates, today_kst())


def test_long_talk_topics_are_picked_more_and_new_topics_still_come(client):
    room_id, (kimjang1, kimjang2, trip, plain) = _room(client, ["김장", "김장", "나들이", "none"])
    _talk(room_id, kimjang1, 30)
    _talk(room_id, kimjang2, 26)
    _talk(room_id, trip, 4)
    _talk(room_id, trip, 6)
    pool = _pool(room_id, [kimjang1, kimjang2, trip, plain])
    # 길게 이야기하신 김장 사진은 4칸, 나머지는 2칸 — 이름표가 없는 사진도 빠지지 않는다
    assert [pool.count(p) for p in (kimjang1, kimjang2, trip, plain)] == [4, 4, 2, 2]


def test_one_long_talk_is_not_enough_to_call_it_a_favorite(client):
    room_id, (kimjang, trip) = _room(client, ["김장", "나들이"])
    _talk(room_id, kimjang, 40)
    _talk(room_id, trip, 5)
    assert sorted(_pool(room_id, [kimjang, trip])) == sorted([kimjang, kimjang, trip, trip])


def test_photo_that_made_her_sad_rests_and_skipped_topic_comes_less(client):
    room_id, (sad, risky, skipped, plain) = _room(client, ["김장", "나들이", "모내기", "none"])
    _talk(room_id, sad, 10, sad=True)  # 많이 슬퍼하셔서 대화를 마친 사진
    _talk(room_id, risky, 10, flag="RISK")
    with SessionLocal() as db:
        for days_ago in (5, 9):  # 모내기 사진을 두 번 넘기심
            db.add(
                DailyPick(
                    room_id=room_id,
                    pick_date=today_kst() - timedelta(days=days_ago),
                    photo_id=skipped,
                    status="SKIPPED",
                    skipped_at=now_kst(),
                )
            )
        db.commit()
    pool = _pool(room_id, [sad, risky, skipped, plain])
    assert [pool.count(p) for p in (sad, risky, skipped, plain)] == [0, 0, 1, 2]
    # 쉬게 할 사진뿐이면 비우지 않고 후보 그대로
    assert _pool(room_id, [sad, risky]) == [sad, risky]
    # 60일이 지난 일은 보지 않는다
    with SessionLocal() as db:
        for session in db.query(TalkSession).filter(TalkSession.room_id == room_id):
            session.started_at = now_kst() - timedelta(days=61)
        db.commit()
    assert _pool(room_id, [sad, risky]).count(sad) == 2
