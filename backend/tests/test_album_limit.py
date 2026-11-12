"""사진첩 상한은 가족방별 한국 날짜 기준이며 같은 요청은 다시 세지 않는다."""

import uuid
from datetime import timedelta

from app.config import ALBUM_PER_DAY, ALBUM_TURNS, now_kst
from app.db import SessionLocal
from app.models import Photo, TalkSession
from tests.conftest import setup_elder


def _create(client, ctx, session_id=None, photo_id=None):
    return client.post(
        "/api/elder/sessions",
        json={
            "session_id": session_id or str(uuid.uuid4()),
            "kind": "ALBUM",
            "photo_id": photo_id or ctx["photo_ids"][0],
        },
    )


def test_album_two_turns_then_ended(client):
    ctx = setup_elder(client)
    created = _create(client, ctx)
    assert created.status_code == 201, created.text
    sid = created.json()["session_id"]
    for turn_no in range(2, ALBUM_TURNS + 1):
        response = client.post(f"/api/elder/sessions/{sid}/turns", json={"text": "네, 기억나요", "input_type": "CHIP"})
        assert response.status_code == 200, response.text
        assert response.json()["state"] == "CONTINUE"
        assert response.json()["turn_no"] == turn_no
    response = client.post(f"/api/elder/sessions/{sid}/turns", json={"text": "네, 기억나요", "input_type": "CHIP"})
    assert response.status_code == 200, response.text
    ended = response.json()
    assert ended["state"] == "ENDED"
    assert ended["end_reason"] == "COMPLETED"
    assert ended["turn_no"] == ALBUM_TURNS
    assert ended["ai"]["question_type"] == "CLOSING"


def test_album_limit_and_memory_allowed(client):
    ctx = setup_elder(client)
    for _ in range(ALBUM_PER_DAY):
        assert _create(client, ctx).status_code == 201
    limited = _create(client, ctx)
    assert limited.status_code == 409
    assert limited.json() == {
        "code": "ALBUM_LIMIT",
        "detail": "오늘은 사진첩 이야기를 다 했어요. 내일 또 해요",
    }
    memory = client.post(
        "/api/elder/sessions",
        json={"session_id": str(uuid.uuid4()), "kind": "MEMORY", "pick_id": ctx["pick"]["pick_id"]},
    )
    assert memory.status_code == 201


def test_album_retry_at_limit(client):
    ctx = setup_elder(client)
    sid = str(uuid.uuid4())
    first = _create(client, ctx, sid)
    assert first.status_code == 201
    for _ in range(ALBUM_PER_DAY - 1):
        assert _create(client, ctx).status_code == 201
    again = _create(client, ctx, sid)
    assert again.status_code == 201
    assert again.json() == first.json()
    assert _create(client, ctx).status_code == 409


def test_album_previous_day_and_other_room_do_not_count(client):
    ctx = setup_elder(client)
    midnight = now_kst().replace(hour=0, minute=0, second=0, microsecond=0)
    for _ in range(ALBUM_PER_DAY):
        created = _create(client, ctx)
        assert created.status_code == 201
        with SessionLocal() as db:
            session = db.get(TalkSession, uuid.UUID(created.json()["session_id"]))
            session.started_at = midnight - timedelta(seconds=1)
            db.commit()
    for _ in range(ALBUM_PER_DAY):
        assert _create(client, ctx).status_code == 201
    assert _create(client, ctx).status_code == 409
    other = setup_elder(client)
    assert _create(client, other).status_code == 201


def test_album_limit_counts_from_kst_midnight(client):
    """한국 0시 1초에 시작한 대화도 오늘로 센다. UTC 0시로 세면 한국 9시 이후엔 어제로 빠져 201 이 된다."""
    ctx = setup_elder(client)
    start = now_kst().replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(seconds=1)
    for _ in range(ALBUM_PER_DAY):
        created = _create(client, ctx)
        assert created.status_code == 201
        with SessionLocal() as db:
            db.get(TalkSession, uuid.UUID(created.json()["session_id"])).started_at = start
            db.commit()
    limited = _create(client, ctx)
    assert limited.status_code == 409
    assert limited.json()["code"] == "ALBUM_LIMIT"


def test_session_kind_and_photo_url(client):
    """회상 화면이 사진첩 대화를 가를 수 있게 kind·photo_url 을 준다. 새로고침(GET)도 같고, 회상은 오늘의 한 장 사진."""
    ctx = setup_elder(client)
    photo_id = next(p for p in ctx["photo_ids"] if p != ctx["pick"]["photo_id"])  # 오늘의 한 장과 다른 사진
    with SessionLocal() as db:
        url = f"/api/media/{db.get(Photo, photo_id).object_key}"
    album = _create(client, ctx, photo_id=photo_id).json()
    assert (album["kind"], album["photo_url"]) == ("ALBUM", url)
    got = client.get(f"/api/elder/sessions/{album['session_id']}").json()
    assert (got["kind"], got["photo_url"]) == ("ALBUM", url)
    memory = client.post(
        "/api/elder/sessions",
        json={"session_id": str(uuid.uuid4()), "kind": "MEMORY", "pick_id": ctx["pick"]["pick_id"]},
    ).json()
    assert (memory["kind"], memory["photo_url"]) == ("MEMORY", ctx["pick"]["photo_url"])
