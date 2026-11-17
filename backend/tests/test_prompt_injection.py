"""AI 호출 경계에서 사용자 글이 JSON 데이터로만 전달되는지 확인한다 (FR-AI-006·D14)."""

import json
from io import BytesIO

import pytest
from PIL import Image

from app.ai import classify, coach
from app.db import SessionLocal
from app.models import Photo
from app.services import storage
from tests.conftest import add_photos, make_room, setup_elder, signup
from tests.test_diary_buddy import INJECTION, claude  # noqa: F401, F811
from tests.test_session_stub import _create
from tests.test_weekly_ai import NOW, WEEK, _talk


def assert_json_data(calls):
    assert calls
    for call in calls:
        assert INJECTION not in call["system"]
        content = call["messages"][0]["content"]
        if isinstance(content, list):
            content = next(item["text"] for item in content if item["type"] == "text")
        data = json.loads(content)
        assert INJECTION in json.dumps(data, ensure_ascii=False)


def test_memory_turn_injection_is_data_and_bad_reply_falls_back(client, claude):
    ctx = setup_elder(client)
    # 시작 질문도 실제 어댑터 경로를 거치되 외부 연결은 가짜 클라이언트로 대체한다.
    claude('{"text":"사진을 보니 어떠세요?","suggestions":[],"signal":"NONE","private":false}')
    sid = _create(client, ctx)["session_id"]
    fake = claude(*['{"text":"점수 100점","suggestions":[],"signal":"NONE","private":false}'] * 2)
    response = client.post(f"/api/elder/sessions/{sid}/turns", json={"text": INJECTION, "input_type": "CHIP"})
    assert response.status_code == 200
    assert response.json()["ai"]["text"] == coach.FALLBACK_QUESTION.text
    assert len(fake.calls) == 2
    assert_json_data(fake.calls)


@pytest.mark.xfail(strict=True, reason="app/ai/classify.py:80 caption·people_note가 LLM JSON에 전달되지 않음")
def test_photo_notes_injection_is_data_and_bad_scene_is_discarded(client, claude):
    signup(client)
    room_id = make_room(client)["room_id"]
    photo_id = add_photos(room_id, 1)[0]
    fake = claude(
        *[
            '{"usable":true,"is_old":true,"season":"unknown","activity":"none",'
            '"category":"none","confidence":0.9,"scene":"점수 100점"}'
        ]
        * 2
    )
    with SessionLocal() as db:
        photo = db.get(Photo, photo_id)
        photo.caption = photo.people_note = INJECTION
        image = BytesIO()
        Image.new("RGB", (8, 8)).save(image, "JPEG")
        storage.put(photo.object_key, image.getvalue())
        assert classify.classify(photo)
        assert photo.activity == "none" and photo.ai_scene is None
    assert len(fake.calls) == 2
    assert_json_data(fake.calls)


def test_weekly_injection_is_data_and_bad_cards_are_discarded(client, claude):
    from sqlalchemy import select

    from app.ai import weekly as ai_weekly
    from app.models import WeeklySummary
    from app.services import weekly

    signup(client)
    room_id = make_room(client)["room_id"]
    with SessionLocal() as db:
        _talk(db, room_id, 10, [("어떤 이야기가 떠오르세요?", INJECTION)])
        db.commit()
        weekly.build(db, room_id, NOW)
        fake = claude(*['{"cards":[{"ref":"a1","answer":"점수 100점이에요.","quote":"공원에 갔어요"}]}'] * 2)
        ai_weekly.summarize(db, room_id, WEEK)
        summary = db.scalar(select(WeeklySummary).where(WeeklySummary.room_id == room_id))
        assert summary.qa_list == []
    assert len(fake.calls) == 1
    assert_json_data(fake.calls)
