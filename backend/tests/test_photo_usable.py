"""가족 사진 응답의 분류 전·후 사용 가능 여부."""

import pytest

from app.config import now_kst
from app.db import SessionLocal
from app.models import Photo
from tests.conftest import add_photos, make_room, signup


@pytest.mark.parametrize("analyzed,usable,expected", [(False, True, None), (True, False, False), (True, True, True)])
def test_photo_usable_response(client, analyzed, usable, expected):
    signup(client)
    room_id = make_room(client)["room_id"]
    photo_id = add_photos(room_id, 1)[0]
    with SessionLocal() as db:
        photo = db.get(Photo, photo_id)
        photo.analyzed_at = now_kst() if analyzed else None
        photo.usable = usable
        db.commit()
    response = client.get(f"/api/rooms/{room_id}/photos")
    assert response.status_code == 200
    photo = next(p for p in response.json()["photos"] if p["photo_id"] == photo_id)
    assert photo["usable"] is expected
