"""어르신 정정 기억 (FR-ME-009) — "김장이 아니라 고사리야"를 새벽 작업이 뽑아 사진에 적고,
다음 대화·문제·주간 이야기에 반영한다.

유료 API 는 부르지 않는다: call_json 을 바꿔 모델 출력을 흉내 낸다.
"""

import uuid
from datetime import date, datetime, time, timedelta
from decimal import Decimal

from sqlalchemy import select

from app.ai import llm, quiz, story
from app.ai import weekly as weekly_ai
from app.ai.schemas import StoryFactItem, StoryFactItems
from app.config import TZ, now_kst, today_kst
from app.db import SessionLocal
from app.models import FamilyRoom, Photo, StoryFact, TalkSession, WeeklySummary
from app.routers.sessions import coach_context
from app.services import weekly
from tests.conftest import add_photos, make_room, signup
from tests.test_story import PLAN

ASKED = "김장하시는 사진 같아요. 김장 자주 하셨어요?"
SAID = "김장이 아니라 고사리 다듬는 거야"
FIX = "이 사진은 고사리 다듬는 거래요."


def _room(client) -> tuple[int, int]:
    signup(client)
    room_id = make_room(client)["room_id"]
    photo_id = add_photos(room_id)[0]
    with SessionLocal() as db:  # 분류 AI 가 '김장'으로 본 사진 — 가족도 김장으로 고쳐 둠
        photo = db.get(Photo, photo_id)
        photo.activity, photo.confidence, photo.analyzed_at = "김장", Decimal("0.90"), now_kst()
        photo.ai_scene, photo.corrected_activity = "마당에서 배추를 절이는 모습", "김장"
        db.commit()
    return room_id, photo_id


def _talk(room_id, day, qa, photo_id=None, *, private=False) -> uuid.UUID:
    turns = []
    for question, said in qa:
        turns.append({"turn_no": len(turns) + 1, "speaker": "AI", "text": question})
        turns.append(
            {
                "turn_no": len(turns) + 1,
                "speaker": "ELDER",
                "text": said,
                "stt_confidence": 0.9,
                "reply_to_turn_no": len(turns),
            }
        )
    sid = uuid.uuid4()
    with SessionLocal() as db:
        db.add(
            TalkSession(
                session_id=sid,
                room_id=room_id,
                kind="MEMORY",
                photo_id=photo_id,
                input_mode="VOICE",
                started_at=datetime.combine(day, time(10), tzinfo=TZ),
                private_flag=private,
                turns=turns,
            )
        )
        db.commit()
    return sid


def _model(*items):
    """story_facts 모델이 (어르신 말, kind, fact, quote) 를 낸 것처럼."""

    def fake(name, data, schema):
        assert name == "story_facts"
        ref = {pair["said"]: pair["ref"] for pair in data["pairs"]}
        return StoryFactItems(
            facts=[StoryFactItem(ref=ref[said], kind=kind, fact=fact, quote=quote) for said, kind, fact, quote in items]
        )

    return fake


def test_check_counts_corrections_apart_and_needs_a_photo():
    pairs = [{"ref": f"a{i}", "question": ASKED, "said": SAID, "photo_id": 7} for i in range(1, 7)]
    pairs.append({"ref": "a7", "question": ASKED, "said": SAID, "photo_id": None})  # 사진 없는 대화
    quote = "고사리 다듬는"
    items = [StoryFactItem(ref=f"a{i}", kind="EVENT", fact="고사리를 다듬으셨대요.", quote=quote) for i in (1, 2, 3)]
    items += [StoryFactItem(ref=f"a{i}", kind="CORRECTION", fact=FIX, quote=quote) for i in (4, 5, 6, 7)]
    kept = story.check(items, pairs)
    # 안부 기억 3개 상한과 따로 정정 2개까지. 사진 없는 대화의 정정(a7)은 버린다
    assert [(pair["ref"], item.kind) for pair, item, _ in kept] == [
        ("a1", "EVENT"),
        ("a2", "EVENT"),
        ("a3", "EVENT"),
        ("a4", "CORRECTION"),
        ("a5", "CORRECTION"),
    ]


def test_correction_is_written_on_the_photo_and_never_asked_back(client, monkeypatch):
    room_id, photo_id = _room(client)
    day = today_kst() - timedelta(days=1)
    sid = _talk(room_id, day, [(ASKED, SAID), ("내일은 뭐 하세요?", PLAN)], photo_id)
    plan = (PLAN, "PLAN", "경로당에 가신다고 하셨어요.", "경로당 가서")
    monkeypatch.setattr(llm, "call_json", _model((SAID, "CORRECTION", FIX, "고사리 다듬는 거야"), plan))
    with SessionLocal() as db:
        assert story.extract(db, room_id, day) == 2
        photo = db.get(Photo, photo_id)
        assert (photo.elder_note, photo.corrected_activity) == (FIX, "none")  # 가족이 고른 '김장'보다 어르신 말
        assert photo.elder_noted_at is not None and photo.corrected_at == photo.elder_noted_at
        # 그 사진에는 활동 문제를 다시 내지 않는다 — AI 가 붙인 '김장'으로도 돌아가지 않는다
        assert quiz.photo_tags(photo)[0] is None
        # 다음 대화: 틀렸다고 하신 AI 짐작(scene)은 넘기지 않고 어르신 말을 넘긴다
        ctx = coach_context(db, db.get(FamilyRoom, room_id), db.get(TalkSession, sid))
        assert ctx.scene is None and ctx.photo["elder_note"] == FIX and ctx.photo["activity"] is None
        # 안부로 이어 묻는 것은 하실 일뿐 — 정정은 묻지 않는다
        picked = story.pick(db, room_id)
        assert picked.kind == "PLAN"
        picked.used_at = now_kst() - timedelta(days=1)  # 어제 물은 셈 치면 오늘 물을 것은 없다
        db.commit()
        assert story.pick(db, room_id) is None
    # 가족 '올린 사진' 응답에도 실린다
    listed = client.get(f"/api/rooms/{room_id}/photos").json()["photos"]
    assert next(p for p in listed if p["photo_id"] == photo_id)["elder_note"] == FIX


def test_correction_on_deleted_or_other_room_photo_is_ignored(client, monkeypatch):
    room_id, photo_id = _room(client)
    day = today_kst() - timedelta(days=1)
    _talk(room_id, day, [(ASKED, SAID)], photo_id)
    assert client.delete(f"/api/rooms/{room_id}/photos/{photo_id}").status_code == 204
    monkeypatch.setattr(llm, "call_json", _model((SAID, "CORRECTION", FIX, "고사리 다듬는 거야")))
    with SessionLocal() as db:
        story.extract(db, room_id, day)
        photo = db.get(Photo, photo_id)
        assert (photo.status, photo.elder_note, photo.corrected_activity) == ("DELETED", None, None)


def test_deleting_the_photo_removes_the_note(client):
    room_id, photo_id = _room(client)
    with SessionLocal() as db:
        photo = db.get(Photo, photo_id)
        photo.elder_note, photo.elder_noted_at = FIX, now_kst()
        db.commit()
    assert client.delete(f"/api/rooms/{room_id}/photos/{photo_id}").status_code == 204
    with SessionLocal() as db:
        photo = db.get(Photo, photo_id)
        assert (photo.elder_note, photo.elder_noted_at) == (None, None)


def _fix_fact(room_id, sid, created, *, turn_no=2) -> None:
    with SessionLocal() as db:
        db.add(
            StoryFact(
                room_id=room_id,
                session_id=sid,
                source_turn_no=turn_no,
                fact_text=FIX,
                kind="CORRECTION",
                fact_date=created.date(),
                expires_at=created + timedelta(days=30),
                created_at=created,
            )
        )
        db.commit()


def _week(room_id) -> WeeklySummary:
    """11/9 주 (11/8 19:00 ~ 11/15 19:00) 집계 + 요약."""
    with SessionLocal() as db:
        weekly.build(db, room_id, datetime(2026, 11, 15, 19, tzinfo=TZ))
        weekly_ai.summarize(db, room_id, date(2026, 11, 9))
        return db.scalar(select(WeeklySummary).where(WeeklySummary.room_id == room_id))


def test_weekly_shows_the_correction_card_once(client):
    room_id, photo_id = _room(client)
    day = date(2026, 11, 12)
    sid = _talk(room_id, day, [(ASKED, SAID), ("뭐 드셨어요?", "잔치국수를 먹었지")], photo_id)
    _fix_fact(room_id, sid, datetime(2026, 11, 13, 4, tzinfo=TZ))  # 다음 날 새벽 작업이 뽑음
    secret = _talk(room_id, day, [(ASKED, SAID)], photo_id, private=True)  # 뽑힌 뒤 비밀로 바뀐 대화 — 안 실린다
    _fix_fact(room_id, secret, datetime(2026, 11, 13, 4, tzinfo=TZ))
    late = _talk(room_id, date(2026, 11, 15), [(ASKED, SAID)], photo_id)  # 일요일 대화 — 월요일 새벽에 뽑혀 다음 주로
    _fix_fact(room_id, late, datetime(2026, 11, 16, 4, tzinfo=TZ))
    row = _week(room_id)
    # 정정 카드가 먼저, 바로잡아 주신 답은 질문·답 카드로 한 번 더 나오지 않는다 (mock 요약은 답을 그대로 따온다)
    assert [(card["question"], card["answer"]) for card in row.qa_list] == [
        (ASKED, FIX),
        ("뭐 드셨어요?", "'잔치국수를 먹었지'라고 하셨어요."),
        (ASKED, f"'{SAID}'라고 하셨어요."),  # 일요일 대화의 답 — 정정으로는 아직 안 뽑혔다
    ]
    card = row.qa_list[0]
    assert card["photo_id"] == photo_id and card["photo_url"].startswith("/api/media/rooms/")
    assert (card["session_id"], card["source_turns"], card["date"]) == (str(sid), [2], "2026-11-12")
    assert row.rule_check_passed


def test_weekly_keeps_the_correction_card_when_ai_fails(client, monkeypatch):
    room_id, photo_id = _room(client)
    sid = _talk(room_id, date(2026, 11, 12), [(ASKED, SAID), ("뭐 드셨어요?", "잔치국수를 먹었지")], photo_id)
    _fix_fact(room_id, sid, datetime(2026, 11, 13, 4, tzinfo=TZ))

    def boom(name, data, schema):
        raise llm.LlmError("시간 초과")

    monkeypatch.setattr(llm, "call_json", boom)
    row = _week(room_id)
    assert [card["answer"] for card in row.qa_list] == [FIX]
    assert (row.model_version, row.rule_check_passed) == ("failed", True)
