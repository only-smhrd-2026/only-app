import uuid

from app.config import now_kst
from app.db import SessionLocal
from app.models import Photo
from tests.conftest import make_room, signup


def test_photo_pages_handle_timestamp_ties_and_reject_invalid_cursors(client):
    signup(client)
    room = make_room(client)["room_id"]
    other_room = make_room(client)["room_id"]
    batch = uuid.uuid4()
    uploaded_at = now_kst()
    with SessionLocal() as db:
        photos = [
            Photo(
                room_id=room,
                upload_batch_id=batch,
                object_key=f"rooms/{room}/{batch}/{i}.jpg",
                source="FAMILY",
                uploaded_at=uploaded_at,
            )
            for i in range(105)
        ]
        foreign = Photo(
            room_id=other_room, upload_batch_id=batch, object_key=f"rooms/{other_room}/{batch}/0.jpg", source="FAMILY"
        )
        deleted = Photo(
            room_id=room,
            upload_batch_id=batch,
            object_key=f"rooms/{room}/{batch}/deleted.jpg",
            source="FAMILY",
            status="DELETED",
        )
        db.add_all([*photos, foreign, deleted])
        db.flush()
        expected = sorted((photo.photo_id for photo in photos), reverse=True)
        invalid = [foreign.photo_id, deleted.photo_id]
        db.commit()

    path = f"/api/rooms/{room}/photos"
    first = client.get(path).json()
    ids = [photo["photo_id"] for photo in first["photos"]]
    assert ids == expected[:100] and first["has_more"] is True
    second = client.get(path, params={"before": ids[-1]}).json()
    assert [photo["photo_id"] for photo in second["photos"]] == expected[100:]
    assert second["has_more"] is False
    for cursor in invalid:
        result = client.get(path, params={"before": cursor})
        assert result.status_code == 404
        assert result.json()["code"] == "PHOTO_NOT_FOUND"
