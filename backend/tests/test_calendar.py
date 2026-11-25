"""11/25 달력 — 가족 일기 달력(GET /rooms/{id}/calendar·/calendar/{date}) · 어르신 지난 가족 소식(…/family-news/past)
· 가족 사진첩 칩(?who=)과 사진마다 붙는 어르신 이야기(talked·quotes·diary_id).

날짜는 한국 날짜로 나뉜다 — 한국 0시 10분(UTC 전날 15시 10분) 일기는 그 한국 날짜에 들어간다.
"""

import uuid
from datetime import date, datetime

from app.config import TZ
from app.db import SessionLocal
from app.models import Diary, FamilyRoom, Photo, TalkSession, WeeklySummary
from app.services import storage
from tests.conftest import add_photos, setup_elder


def _put(room_id, at, author="FAMILY", *, status="POSTED", heard=False, photo_id=None):
    """그 시각(한국)에 올라온 일기. 가족 일기면 방장이 쓴 것."""
    with SessionLocal() as db:
        diary = Diary(
            room_id=room_id,
            author_type=author,
            author_user_id=db.get(FamilyRoom, room_id).owner_user_id if author == "FAMILY" else None,
            body="오늘 이야기",
            mood="GOOD",
            illustration_type="PHOTO" if photo_id else "NONE",
            photo_id=photo_id,
            request_id=uuid.uuid4(),
            status=status,
            posted_at=at,
            elder_read_at=at if heard else None,
        )
        db.add(diary)
        db.commit()
        return diary.diary_id


def kst(m, d, h=12, mi=0):
    return datetime(2026, m, d, h, mi, tzinfo=TZ)


def test_family_calendar_month_and_day(client):
    room_id = setup_elder(client)["room_id"]
    photo = add_photos(room_id, 1)[0]
    _put(room_id, kst(10, 30, 21), "ELDER")
    morning = _put(room_id, kst(11, 3, 9), photo_id=photo)
    night = _put(room_id, kst(11, 3, 23, 30), "ELDER")
    after_midnight = _put(room_id, kst(11, 4, 0, 10))  # UTC 로는 11월 3일
    _put(room_id, kst(11, 5), status="DELETED")
    url = f"/api/rooms/{room_id}/calendar"

    latest = client.get(url)  # 달을 안 주면 일기가 있는 가장 최근 달
    assert latest.status_code == 200, latest.text
    body = latest.json()
    assert (body["month"], body["prev_month"], body["next_month"]) == ("2026-11", "2026-10", None)
    assert [(d["date"], d["count"]) for d in body["days"]] == [("2026-11-03", 2), ("2026-11-04", 1)]
    assert body["days"][0]["thumb_url"].startswith("/api/media/") and body["days"][1]["thumb_url"] is None

    october = client.get(url, params={"month": "2026-10"}).json()
    assert [d["date"] for d in october["days"]] == ["2026-10-30"]
    assert (october["prev_month"], october["next_month"]) == (None, "2026-11")
    assert client.get(url, params={"month": "2026-13"}).status_code == 422

    day = client.get(f"{url}/2026-11-03").json()
    assert [d["diary_id"] for d in day["diaries"]] == [morning, night]  # 아침 → 저녁
    assert (day["prev_date"], day["next_date"]) == ("2026-10-30", "2026-11-04")
    assert [d["diary_id"] for d in client.get(f"{url}/2026-11-04").json()["diaries"]] == [after_midnight]
    assert client.get(f"{url}/2026-10-30").json()["prev_date"] is None

    setup_elder(client)  # 다른 가족방 사람에게는 있는지도 모르게 404
    assert client.get(url).status_code == 404
    assert client.get(f"{url}/2026-11-03").status_code == 404


def test_elder_past_news_months_skip_empty_ones(client):
    room_id = setup_elder(client)["room_id"]
    september = _put(room_id, kst(9, 10), heard=True)
    november = _put(room_id, kst(11, 2), heard=True)
    _put(room_id, kst(11, 3))  # 아직 안 들은 일기는 새 소식에만
    _put(room_id, kst(11, 4), "ELDER")
    path = "/api/elder/family-news/past"

    now = client.get(path).json()
    assert [d["diary_id"] for d in now["diaries"]] == [november]
    assert (now["month"], now["prev_month"], now["next_month"]) == ("2026-11", "2026-09", None)  # 빈 10월은 건너뛴다
    sep = client.get(path, params={"month": "2026-09"}).json()
    assert [d["diary_id"] for d in sep["diaries"]] == [september]
    assert (sep["prev_month"], sep["next_month"]) == (None, "2026-11")


def test_album_who_chips_and_elder_story(client):
    ctx = setup_elder(client)
    room_id, base = ctx["room_id"], set(ctx["photo_ids"])  # 시작할 때 있던 가족 사진 3장
    memory, quiet = add_photos(room_id, 2)
    extra = {}
    with SessionLocal() as db:
        for name, source in (("news", "FAMILY_DIARY"), ("orphan", "FAMILY_DIARY"), ("elder", "ELDER_CAMERA")):
            key = f"rooms/{room_id}/{uuid.uuid4()}.jpg"
            storage.put(key, b"\xff\xd8\xff\xd9")
            photo = Photo(room_id=room_id, upload_batch_id=uuid.uuid4(), object_key=key, source=source)
            db.add(photo)
            db.flush()
            extra[name] = photo.photo_id
        # 어르신이 memory 로 말씀하신 대화 + 그 주간 이야기 카드
        turns = [{"turn_no": 1, "speaker": "ELDER", "text": "그때 그 사진관"}]
        db.add(
            TalkSession(
                session_id=uuid.uuid4(),
                room_id=room_id,
                kind="MEMORY",
                photo_id=memory,
                input_mode="VOICE",
                turns=turns,
            )
        )
        card = {
            "photo_id": memory,
            "date": "2026-11-18",
            "question": "어디서 찍으셨어요?",
            "answer": "읍내 사진관이래요",
        }
        db.add(
            WeeklySummary(
                room_id=room_id,
                week_start=date(2026, 11, 16),
                memory_days=1,
                diary_days=0,
                qa_list=[card],
                recall_check={},
                mood_trend=[],
                talk_volume={},
                diaries=[],
                rule_check_passed=True,
                model_version="test",
            )
        )
        db.commit()
    news_diary = _put(room_id, kst(11, 20), photo_id=extra["news"])
    url = f"/api/rooms/{room_id}/photos"

    every = {p["photo_id"]: p for p in client.get(url).json()["photos"]}
    assert set(every) == base | {memory, quiet, extra["news"], extra["elder"]}  # 올리다 그만둔 오늘 소식 사진은 없다
    assert every[memory]["talked"]
    assert every[memory]["quotes"] == [
        {"day": "2026-11-18", "question": "어디서 찍으셨어요?", "answer": "읍내 사진관이래요"}
    ]
    assert not every[quiet]["talked"] and every[quiet]["quotes"] == []
    assert every[extra["news"]]["diary_id"] == news_diary and every[memory]["diary_id"] is None

    elder = [p["photo_id"] for p in client.get(url, params={"who": "ELDER"}).json()["photos"]]
    family = {p["photo_id"] for p in client.get(url, params={"who": "FAMILY"}).json()["photos"]}
    assert elder == [extra["elder"]] and family == base | {memory, quiet, extra["news"]}


def test_elder_album_shows_who_sent(client):
    """어르신 사진첩 사진 칸 이름표 (11/25) — 가족 사진은 올린 사람 '별명 (이름)', 올린 사람을 모르면 null."""
    from sqlalchemy import update

    from app.models import RoomMember, User

    ctx = setup_elder(client)
    sent, unknown = ctx["photo_ids"][:2]
    with SessionLocal() as db:
        owner = db.get(FamilyRoom, ctx["room_id"]).owner_user_id
        db.execute(
            update(RoomMember)
            .where(RoomMember.room_id == ctx["room_id"], RoomMember.user_id == owner)
            .values(nickname="큰딸")
        )
        db.execute(update(Photo).where(Photo.photo_id == sent).values(uploaded_by=owner))
        name = db.get(User, owner).name
        db.commit()
    photos = {p["photo_id"]: p for p in client.get("/api/elder/album").json()["photos"]}
    assert photos[sent]["uploader_name"] == f"큰딸 ({name})"
    assert photos[unknown]["uploader_name"] is None
