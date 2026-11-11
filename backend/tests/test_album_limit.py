"""사진첩 상한은 가족방별 한국 날짜 기준이며 같은 요청은 다시 세지 않는다."""

import uuid
from datetime import timedelta

from app.config import ALBUM_PER_DAY, now_kst
from app.db import SessionLocal
from app.models import TalkSession
from tests.conftest import setup_elder


def _create(client, ctx, session_id=None):
    return client.post(
        "/api/elder/sessions",
        json={
            "session_id": session_id or str(uuid.uuid4()),
            "kind": "ALBUM",
            "photo_id": ctx["photo_ids"][0],
        },
    )


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
