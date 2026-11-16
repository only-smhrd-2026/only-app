"""사용 지표의 KST 범위·비율·빈 집계·개인정보 비출력을 확인한다."""

import json
import sys
import uuid
from datetime import date, datetime, timedelta, timezone

import pytest

from app.config import TZ
from app.db import SessionLocal
from app.models import DailyPick, Diary, FamilyRoom, MoodCheck, TalkSession
from scripts import usage_report
from tests.conftest import add_photos, make_room, signup

SECRET = "파란우산비밀문장"
START = date(2026, 11, 23)
END = date(2026, 11, 27)
AT = datetime(2026, 11, 23, tzinfo=TZ)


def test_report_metrics_and_private_text_never_printed(client, monkeypatch, capsys):
    signup(client)
    room = make_room(client)["room_id"]
    photo = add_photos(room, 1)[0]
    with SessionLocal() as db:
        for i, status in enumerate(("COMPLETED", "SKIPPED", "EXPIRED", "PENDING")):
            db.add(DailyPick(room_id=room, photo_id=photo, pick_date=START + timedelta(days=i), status=status))
        for i, (kind, reason, turns, seconds) in enumerate(
            [
                ("MEMORY", "COMPLETED", 2, 120),
                ("ALBUM", "LIMIT", 4, 60),
                ("DIARY", "USER_STOP", 0, 0),
                ("MEMORY", None, 1, None),
            ]
        ):
            db.add(
                TalkSession(
                    session_id=uuid.uuid4(),
                    room_id=room,
                    kind=kind,
                    input_mode="VOICE",
                    started_at=(AT + timedelta(days=i % 2)).astimezone(timezone.utc),
                    end_reason=reason,
                    turn_count=turns,
                    duration_sec=seconds,
                    turns=[{"speaker": "ELDER", "text": SECRET}] if turns else [],
                )
            )
        for when in (AT - timedelta(microseconds=1), AT + timedelta(days=5)):
            db.add(
                TalkSession(session_id=uuid.uuid4(), room_id=room, kind="MEMORY", input_mode="VOICE", started_at=when)
            )
        owner = db.get(FamilyRoom, room).owner_user_id
        for author, read, status in [
            ("ELDER", False, "POSTED"),
            ("FAMILY", True, "POSTED"),
            ("FAMILY", False, "POSTED"),
            ("ELDER", False, "DELETED"),
        ]:
            db.add(
                Diary(
                    room_id=room,
                    author_type=author,
                    author_user_id=owner if author == "FAMILY" else None,
                    body=SECRET,
                    mood="GOOD",
                    illustration_type="NONE",
                    request_id=uuid.uuid4(),
                    posted_at=AT,
                    status=status,
                    elder_read_at=AT if read else None,
                )
            )
        db.add(MoodCheck(room_id=room, check_date=END, answers=[0] * 8, total=0, level="USUAL"))
        db.commit()
        result = usage_report.report(db, room, START, END)
    assert [result[f"picks_{s}"] for s in ("completed", "skipped", "expired", "pending")] == [1] * 4
    assert [result[f"sessions_{s}"] for s in ("memory", "album", "diary")] == [2, 1, 1]
    assert (result["sessions_total"], result["completion_rate"], result["unfinished"]) == (4, 0.5, 1)
    assert (result["avg_turn_count"], result["avg_duration_sec"], result["elder_spoke_sessions"]) == (1.75, 60, 3)
    assert (result["diaries_elder"], result["diaries_family"], result["family_diary_read_rate"]) == (1, 2, 0.5)
    assert (result["talked_days"], result["diary_days"], result["elder_diary_days"], result["mood_checks"]) == (
        2,
        1,
        1,
        1,
    )
    assert SECRET not in json.dumps(result, ensure_ascii=False)
    monkeypatch.setattr(sys, "argv", ["usage_report", "--room-id", str(room), "--from", str(START), "--to", str(END)])
    usage_report.main()
    output = capsys.readouterr().out
    assert SECRET not in output and "테스터" not in output and "순자" not in output
    assert "sessions_total" in output and "completion_rate" in output


def test_empty_report_and_invalid_range(client):
    signup(client)
    room = make_room(client)["room_id"]
    with SessionLocal() as db:
        result = usage_report.report(db, room, START, END)
        assert all(value == 0 for key, value in result.items() if key not in ("room_id", "from", "to"))
        with pytest.raises(ValueError):
            usage_report.report(db, room, END, START)


def test_cli_defaults_to_active_rooms(client, monkeypatch, capsys):
    signup(client)
    active, closed = make_room(client)["room_id"], make_room(client)["room_id"]
    with SessionLocal() as db:
        db.get(FamilyRoom, closed).status = "CLOSED"
        db.commit()
    seen = []
    monkeypatch.setattr(usage_report, "report", lambda db, room, start, end: seen.append(room) or {"room_id": room})
    monkeypatch.setattr(sys, "argv", ["usage_report", "--from", str(START), "--to", str(END)])
    usage_report.main()
    assert active in seen and closed not in seen
