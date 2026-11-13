"""11/13 DB 변경 (D57): 새 값은 저장되고 이상한 값은 DB 가 막는지, 서버용 ALTER 파일이 다시 돌아도 되는지."""

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.config import ROOT, now_kst, today_kst
from app.db import SessionLocal, engine
from app.models import Diary, FamilyRoom, MoodCheck, Notification, TalkSession
from tests.conftest import make_room, signup

MIGRATION = ROOT / "db" / "migrations" / "20261113_mentoring.sql"


@pytest.fixture
def room_id(client):
    signup(client)
    return make_room(client)["room_id"]


def _session(room_id, flag):
    return TalkSession(session_id=uuid.uuid4(), room_id=room_id, kind="MEMORY", input_mode="VOICE", emotion_flag=flag)


def _notice(room_id, kind):
    return Notification(room_id=room_id, target_type="FAMILY", kind=kind, title="전화 한 통 드려 보세요")


def _diary(room_id, **kw):
    base = {"author_type": "ELDER", "body": "일기", "mood": "SUNNY", "illustration_type": "NONE"}
    return Diary(room_id=room_id, request_id=uuid.uuid4(), **base, **kw)


def _check(room_id, answers=(0, 1, 0, 2, 0, 0, 1, 0), total=4, level="USUAL"):
    answers = list(answers) if isinstance(answers, tuple) else answers
    return MoodCheck(room_id=room_id, check_date=today_kst(), answers=answers, total=total, level=level)


def test_new_values_saved(room_id):
    with SessionLocal() as db:
        diary = _diary(room_id)
        db.add_all([_session(room_id, f) for f in ("SAD", "LOW", "RISK")])
        db.add_all([_notice(room_id, "MOOD_URGENT"), _notice(room_id, "MOOD_LOW_2D"), diary, _check(room_id)])
        db.commit()
        assert diary.reactions == []  # 기본값
        assert db.get(FamilyRoom, room_id).mood_check_consent_at is None
        diary.reactions = [{"by": "FAMILY", "user_id": 1, "kind": "HEART", "at": now_kst().isoformat()}]
        db.commit()
        db.refresh(diary)
        assert diary.reactions[0]["kind"] == "HEART"


@pytest.mark.parametrize(
    "bad",
    [
        pytest.param(lambda r: _session(r, "ANGRY"), id="emotion"),
        pytest.param(lambda r: _notice(r, "MOOD_BAD"), id="kind"),
        pytest.param(lambda r: _diary(r, reactions={"by": "ELDER"}), id="reactions-not-array"),
        pytest.param(lambda r: _check(r, answers=(0,) * 7), id="answers-7"),
        pytest.param(lambda r: _check(r, answers={"q1": 0}), id="answers-not-array"),
        pytest.param(lambda r: _check(r, total=25), id="total"),
        pytest.param(lambda r: _check(r, level="OK"), id="level"),
    ],
)
def test_bad_values_blocked(room_id, bad):
    with SessionLocal() as db:
        db.add(bad(room_id))
        with pytest.raises(IntegrityError):
            db.commit()


def test_one_check_per_day(room_id):
    with SessionLocal() as db:
        db.add(_check(room_id))
        db.commit()
        db.add(_check(room_id, total=6, level="DOWN"))
        with pytest.raises(IntegrityError):
            db.commit()


def test_migration_reruns_on_current_schema():
    """배포 서버용 ALTER 파일: 이미 새 모양인 DB 에서도 오류 없이 돌고, CHECK 를 겹쳐 만들지 않는다(이름이 맞음)."""
    count = text(
        "SELECT count(*) FROM pg_constraint WHERE contype = 'c'"
        " AND conrelid IN ('sessions'::regclass, 'notifications'::regclass, 'diaries'::regclass)"
    )
    with engine.connect() as conn:
        before = conn.execute(count).scalar()
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        conn.exec_driver_sql(MIGRATION.read_text("utf-8"))
        conn.exec_driver_sql(MIGRATION.read_text("utf-8"))
        assert conn.execute(count).scalar() == before
