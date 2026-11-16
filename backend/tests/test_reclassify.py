"""재분류 대상만 초기화하고 나머지 분류·정정 칸을 보존하는지 확인한다."""

import sys

import pytest

from app.config import now_kst, settings
from app.db import SessionLocal
from app.models import Photo
from scripts import reclassify
from tests.conftest import add_photos, make_room, signup


def test_reset_only_old_active_family_and_preserves_other_columns(client):
    signup(client)
    room = make_room(client)["room_id"]
    ids = add_photos(room, 7)
    current = f"{settings.LLM_MODEL}/{reclassify.PROMPT_VERSION}"[:30]
    with SessionLocal() as db:
        for pid in ids:
            photo = db.get(Photo, pid)
            photo.analyzed_at = now_kst()
            photo.model_version = "old/v1"
            photo.caption = "비밀 사진 설명"
            photo.ai_scene = "비밀 AI 모습"
            photo.activity = "바닷가"
            photo.corrected_activity = "여행"
            photo.corrected_at = now_kst()
        db.get(Photo, ids[1]).model_version = current
        db.get(Photo, ids[2]).analyzed_at = None
        db.get(Photo, ids[3]).source = "ELDER_CAMERA"
        db.get(Photo, ids[4]).source = "FAMILY_DIARY"
        db.get(Photo, ids[5]).status = "DELETED"
        db.get(Photo, ids[6]).model_version = None
        db.commit()
        before = {
            pid: {col.name: getattr(db.get(Photo, pid), col.name) for col in Photo.__table__.columns} for pid in ids
        }
        assert reclassify.reset(db, room, dry_run=True) == 2
        db.expire_all()
        assert all(db.get(Photo, pid).analyzed_at == before[pid]["analyzed_at"] for pid in ids)
        assert reclassify.reset(db, room) == 2
        db.expire_all()
        for pid in ids:
            after = {col.name: getattr(db.get(Photo, pid), col.name) for col in Photo.__table__.columns}
            expected = before[pid] | ({"analyzed_at": None} if pid in (ids[0], ids[6]) else {})
            assert after == expected
        assert reclassify.reset(db, room) == 0
        assert reclassify.reset(db, -1) == 0


def test_room_filter_and_cli_privacy(client, monkeypatch, capsys):
    signup(client)
    room, other_room = make_room(client)["room_id"], make_room(client)["room_id"]
    first, other = add_photos(room, 1)[0], add_photos(other_room, 1)[0]
    with SessionLocal() as db:
        for pid in (first, other):
            db.get(Photo, pid).analyzed_at = now_kst()
            db.get(Photo, pid).caption = "비밀 사진 설명"
        db.commit()
    monkeypatch.setattr(sys, "argv", ["reclassify", "--room-id", str(room), "--dry-run"])
    reclassify.main()
    output = capsys.readouterr().out
    assert "대상 수: 1" in output and "비밀 사진 설명" not in output
    with SessionLocal() as db:
        assert db.get(Photo, first).analyzed_at is not None
        assert reclassify.reset(db, room) == 1
        assert db.get(Photo, other).analyzed_at is not None


def test_deploy_guard_before_opening_database(monkeypatch):
    monkeypatch.setattr(settings, "APP_ENV", "deploy")
    monkeypatch.setattr(sys, "argv", ["reclassify", "--dry-run"])
    monkeypatch.setattr(reclassify, "SessionLocal", lambda: pytest.fail("보호 검사 전에 DB를 열면 안 됩니다"))
    with pytest.raises(SystemExit) as exc:
        reclassify.main()
    assert exc.value.code == 1


def test_force_guard_and_daily_cap_message(client, monkeypatch, capsys):
    monkeypatch.setattr(settings, "APP_ENV", "deploy")
    monkeypatch.setattr(sys, "argv", ["reclassify", "--force"])
    monkeypatch.setattr(reclassify, "reset", lambda *args: reclassify.CLASSIFY_PER_DAY + 1)
    reclassify.main()
    assert "하루 상한이라 며칠에 나눠 분류돼요" in capsys.readouterr().out
