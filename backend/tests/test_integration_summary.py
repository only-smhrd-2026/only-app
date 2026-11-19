"""꼬마심심이 연동 (FR-API-001~003): 기본값은 꺼짐, 키 인증과 틀린 키 제한, 동의한 방만, 나가는 칸 고정, 방장만 동의."""

import logging
import os
import subprocess
import sys
import uuid
from datetime import date, datetime, timedelta

import pytest
from sqlalchemy import select

from app import security
from app.config import LOGIN_FAIL_PER_EMAIL, LOGIN_FAIL_WINDOW_SEC, ROOT, TZ, Settings, settings
from app.db import SessionLocal
from app.models import FamilyRoom, TalkSession, WeeklySummary
from app.routers import integration
from app.services import weekly
from tests.conftest import make_room, signup
from tests.test_room_members import join, login
from tests.test_weekly import NOW, _at, _diary

KEY = "test-only-integration-key-0123456789"
AUTH = {"Authorization": f"Bearer {KEY}"}
PATH = "/api/integration/summary"
WEEK = "2026-11-09"  # tests.test_weekly.NOW(11/15 일요일 19시)에 닫히는 주의 월요일
# 밖으로 나가는 칸 전부. 늘리려면 기업과 계약을 다시 확인한 뒤에 (FR-API-002)
KEYS = {
    "elder",
    "week_start",
    "memory_days",
    "diary_days",
    "mood_trend",
    "talk_volume_trend",
    "sad_talk_count",
    "consent_scope",
}
SECRET = "파란우산비밀문장"
NO_ROOM = 999_999_999


@pytest.fixture
def on(monkeypatch):
    """연동을 켠 서버 — 키가 들어 있다."""
    monkeypatch.setattr(settings, "INTEGRATION_API_KEY", KEY)


def _summary(client, elder, week=WEEK, headers=AUTH):
    return client.get(PATH, params={"elder": elder, "week": week}, headers=headers)


def _consent(client, room_id, scope="SUMMARY_ONLY"):
    return client.patch(f"/api/rooms/{room_id}/integration", json={"integration_scope": scope})


def _talk(db, room_id, at, text="네", flag="NONE", private=False, speaker="ELDER"):
    db.add(
        TalkSession(
            session_id=uuid.uuid4(),
            room_id=room_id,
            kind="MEMORY",
            input_mode="VOICE",
            started_at=at,
            emotion_flag=flag,
            private_flag=private,
            turns=[{"turn_no": 1, "speaker": speaker, "text": text}],
        )
    )


def test_off_unless_the_server_has_a_key(client, monkeypatch):
    """FR-API-003: 키를 넣지 않은 서버(기본값)는 무엇을 보내도 등록 안 된 주소와 똑같은 404."""
    assert Settings.model_fields["INTEGRATION_API_KEY"].default == ""
    monkeypatch.setattr(settings, "INTEGRATION_API_KEY", "")  # 내 PC .env 에 키가 있어도 꺼진 서버로
    signup(client)
    room_id = make_room(client)["room_id"]
    assert _consent(client, room_id).status_code == 200  # 동의한 방이 있어도 안 열린다
    unknown = client.get("/api/integration/no-such-address")
    assert unknown.status_code == 404
    for headers in ({}, AUTH):
        for params in ({"elder": room_id, "week": WEEK}, {}, {"elder": "x", "week": "어제"}):
            response = client.get(PATH, params=params, headers=headers)
            assert (response.status_code, response.json()) == (404, unknown.json())


def test_server_does_not_start_with_a_short_key():
    """틀린 키 제한은 IP 별이라, 맞히기를 실제로 막는 것은 키 길이다 — 32자보다 짧으면 서버가 뜨지 않는다."""

    def start(key):
        command = [sys.executable, "-c", "import app.config"]
        env = os.environ | {"INTEGRATION_API_KEY": key}
        return subprocess.run(command, cwd=ROOT / "backend", env=env, capture_output=True, encoding="utf-8")

    refused = start("k" * 31)
    assert refused.returncode != 0 and "INTEGRATION_API_KEY 는 32자 이상" in refused.stderr
    assert start("k" * 32).returncode == 0
    assert start("").returncode == 0  # 빈 값 = 꺼짐


def test_wrong_key_is_401_and_repeated_wrong_keys_block_the_ip(client, on, monkeypatch):
    current = 1000
    monkeypatch.setattr(security, "monotonic", lambda: current)
    wrong = [{}, {"Authorization": "Bearer wrong"}, {"Authorization": f"Basic {KEY}"}, {"Authorization": KEY}]
    wrong += [{"Authorization": f"Bearer {KEY}x"}, {"Authorization": f"Bearer {KEY[:-1]}"}]
    for n in range(LOGIN_FAIL_PER_EMAIL):
        # elder·week 를 안 보내도 422 가 아니라 401 — 키를 모르면 주소의 모양도 알 수 없다
        response = client.get(PATH, headers=wrong[n % len(wrong)])
        assert (response.status_code, response.json()["code"]) == (401, "INTEGRATION_KEY_INVALID")
    blocked = _summary(client, NO_ROOM)  # 막힌 동안에는 맞는 키도 막힌다
    assert (blocked.status_code, blocked.json()["code"]) == (429, "TOO_MANY_ATTEMPTS")
    current += LOGIN_FAIL_WINDOW_SEC
    assert _summary(client, NO_ROOM).json()["code"] == "ELDER_NOT_FOUND"  # 시간이 지나면 풀린다


def test_only_consented_rooms_answer(client, on):
    signup(client)
    room_id = make_room(client)["room_id"]
    with SessionLocal() as db:
        weekly.build(db, room_id, NOW)  # 요약 줄은 있다
    unknown, hidden = _summary(client, NO_ROOM), _summary(client, room_id)
    assert (hidden.status_code, hidden.json()["code"]) == (404, "ELDER_NOT_FOUND")
    assert hidden.json() == unknown.json()  # 동의하지 않은 방이 있는지도 드러나지 않는다
    assert _consent(client, room_id).status_code == 200
    assert _summary(client, room_id).status_code == 200
    with SessionLocal() as db:
        db.get(FamilyRoom, room_id).status = "CLOSED"
        db.commit()
    assert _summary(client, room_id).json() == unknown.json()  # 닫힌 방
    with SessionLocal() as db:
        db.get(FamilyRoom, room_id).status = "ACTIVE"
        db.commit()
    assert _consent(client, room_id, "NONE").status_code == 200
    assert _summary(client, room_id).json() == unknown.json()  # 동의를 거두면 바로 닫힌다


def test_week_is_a_monday_that_has_a_summary(client, on):
    signup(client)
    room_id = make_room(client)["room_id"]
    assert _consent(client, room_id).status_code == 200
    with SessionLocal() as db:
        weekly.build(db, room_id, NOW)
    for bad in ("2026-11-10", "2026-11-15", "어제", ""):
        response = _summary(client, room_id, bad)
        assert (response.status_code, response.json()["code"]) == (422, "VALIDATION")
    assert client.get(PATH, params={"week": WEEK}, headers=AUTH).status_code == 422  # elder 없음
    assert _summary(client, 2**63).status_code == 422  # DB 번호 범위 밖 — 500 이 아니다
    for no_row in ("2026-11-02", "2026-11-16", "0001-01-01", "9999-12-27"):  # 끝의 둘도 월요일 — 500 이 아니라 404
        response = _summary(client, room_id, no_row)
        assert (response.status_code, response.json()["code"]) == (404, "NO_SUMMARY")


def test_summary_is_numbers_and_moods_only(client, on, caplog):
    signup(client)
    room_id = make_room(client)["room_id"]
    assert _consent(client, room_id).status_code == 200
    with SessionLocal() as db:
        _talk(db, room_id, _at(10), "김장하던 날이 생각나요")
        _talk(db, room_id, _at(11), "요즘 기운이 없어", flag="LOW")
        _talk(db, room_id, _at(12), SECRET, flag="RISK")
        _talk(db, room_id, _at(12, 11), "애들한테는 말하지 마", flag="LOW", private=True)
        # 말하지 말라고 하신 위급 대화 — 가족에게는 알리지만(D55 ③) 밖으로는 세지 않는다
        _talk(db, room_id, _at(13), "아무한테도 말하지 마", flag="RISK", private=True)
        _talk(db, room_id, _at(14), flag="LOW", speaker="AI")  # 어르신이 말하지 않은 대화 — 기록으로 치지 않는다
        _talk(db, room_id, _at(8, 18, 59), flag="LOW")  # 지난주에 닫힌 대화
        _talk(db, room_id, NOW, flag="LOW")  # 다음 주로 넘어간 대화
        _talk(db, room_id, datetime(2026, 10, 27, 10, tzinfo=TZ), "하나 둘")
        _talk(db, room_id, datetime(2026, 10, 13, 10, tzinfo=TZ), "하나 둘 셋 넷")  # 5주 전 — 추이에 안 나온다
        _diary(db, room_id, _at(11, 20, 5))
        db.commit()
        for weeks_ago in range(5):
            weekly.build(db, room_id, NOW - timedelta(days=7 * weeks_ago))
        row = db.scalar(
            select(WeeklySummary).where(WeeklySummary.room_id == room_id, WeeklySummary.week_start == date(2026, 11, 9))
        )
        row.qa_list = [{"question": SECRET, "answer": SECRET, "quote": SECRET}]  # 가족에게만 보이는 칸
        row.notes = {"care": SECRET}
        db.commit()
    caplog.set_level(logging.INFO)
    response = _summary(client, room_id)
    assert response.status_code == 200
    assert set(response.json()) == KEYS
    assert response.json() == {
        "elder": room_id,
        "week_start": WEEK,
        "memory_days": 4,  # '말하지 마' 대화도 이야기한 날로는 센다 (주간 집계와 같은 값)
        "diary_days": 1,
        "mood_trend": [{"date": f"2026-11-{day:02d}", "mood": "GOOD" if day == 11 else None} for day in range(9, 16)],
        "talk_volume_trend": [
            {"week_start": "2026-10-19", "words": 0, "turns": 0, "avg_words": 0},
            {"week_start": "2026-10-26", "words": 2, "turns": 1, "avg_words": 2.0},
            {"week_start": "2026-11-02", "words": 1, "turns": 1, "avg_words": 1.0},
            {"week_start": WEEK, "words": 7, "turns": 3, "avg_words": 2.3},
        ],
        "sad_talk_count": 2,
        "consent_scope": "SUMMARY_ONLY",
    }
    for original in (SECRET, "순자", "할머니", "테스터", "저장하면 안 되는 테스트 본문"):  # 말·이름·호칭·일기 글
        assert original not in response.text
    assert f"integration summary room={room_id} week={WEEK}" in caplog.text
    assert KEY not in caplog.text and SECRET not in caplog.text


def test_contract_is_written_in_openapi(client):
    spec = client.get("/openapi.json").json()
    operation = spec["paths"][PATH]["get"]
    assert operation["security"] == [{"HTTPBearer": []}]
    assert {"200", "401", "404", "422", "429"} <= set(operation["responses"])
    out = spec["components"]["schemas"]["IntegrationSummaryOut"]
    assert set(out["properties"]) == KEYS and out["additionalProperties"] is False


def test_only_the_owner_gives_and_withdraws_consent(client, monkeypatch):
    first = datetime(2026, 11, 19, 9, 30, tzinfo=TZ)
    monkeypatch.setattr(integration, "now_kst", lambda: first)
    owner = signup(client)
    room_id = make_room(client)["room_id"]

    def saved():
        with SessionLocal() as db:
            room = db.get(FamilyRoom, room_id)
            return room.integration_scope, room.integration_consent_at

    assert saved() == ("NONE", None)  # 가족방을 만들면 연동은 꺼져 있다 (FR-API-001)
    given = _consent(client, room_id)
    assert given.status_code == 200
    assert given.json() == {
        "integration_scope": "SUMMARY_ONLY",
        "integration_consent_at": first.isoformat(),
        "external_user_id": None,
    }
    monkeypatch.setattr(integration, "now_kst", lambda: first + timedelta(hours=1))
    assert _consent(client, room_id).json() == given.json()  # 두 번 눌러도 동의 시각은 처음 그대로
    join(client, room_id)  # 손주로 로그인된다
    member = _consent(client, room_id, "NONE")
    assert (member.status_code, member.json()["code"]) == (403, "NOT_OWNER")
    signup(client)  # 남의 가족
    stranger = _consent(client, room_id, "NONE")
    assert (stranger.status_code, stranger.json()["code"]) == (404, "ROOM_NOT_FOUND")
    client.cookies.clear()
    assert _consent(client, room_id, "NONE").status_code == 401
    assert saved() == ("SUMMARY_ONLY", first)
    login(client, owner)
    assert _consent(client, room_id, "ALL").status_code == 422
    withdrawn = _consent(client, room_id, "NONE")
    assert withdrawn.json() == {"integration_scope": "NONE", "integration_consent_at": None, "external_user_id": None}
    assert saved() == ("NONE", None)
