import uuid
from datetime import timedelta

from app.config import now_kst
from app.db import SessionLocal
from app.models import Photo
from app.routers import photos as photos_api
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


def test_photo_pages_follow_upload_time_without_gaps_or_repeats(client, monkeypatch):
    """올린 시각이 번호 순서와 어긋나거나 여러 장이 같아도, 끝까지 넘기면 빠지거나 겹치는 사진이 없다 (#244 다듬기)."""
    signup(client)
    room = make_room(client)["room_id"]
    batch = uuid.uuid4()
    base = now_kst()
    # 저장한 차례(= photo_id 가 커지는 순서)로 적은 '몇 분 전에 올렸나'.
    # 나중에 저장했는데 더 옛날인 사진, 먼저 저장했는데 가장 새 사진,
    # 같은 시각 사진(5분 전 5장·0분 전 3장·3분 전 2장)이 섞여 있다
    minutes_ago = [5, 0, 5, 3, 0, 5, 9, 3, 5, 0, 5, 1]
    with SessionLocal() as db:
        rows = []
        for i, minutes in enumerate(minutes_ago):
            photo = Photo(
                room_id=room,
                upload_batch_id=batch,
                object_key=f"rooms/{room}/{batch}/{i}.jpg",
                source="FAMILY",
                uploaded_at=base - timedelta(minutes=minutes),
            )
            db.add(photo)
            db.flush()  # 한 장씩 저장해 photo_id 가 이 차례대로 커지게
            rows.append((photo.uploaded_at, photo.photo_id))
        db.commit()
    ids = [photo_id for _, photo_id in rows]
    assert ids == sorted(ids)
    # 새로 올린 것 먼저, 같은 시각이면 번호 큰 것 먼저
    expected = [photo_id for _, photo_id in sorted(rows, reverse=True)]
    # 번호 순서와 다르다 — 번호로만 줄 세우거나 번호로만 다음 쪽을 자르면 아래에서 틀린다
    assert expected != ids[::-1]

    path = f"/api/rooms/{room}/photos"
    # 12장을 1·4·5장씩: 쪽 경계가 같은 시각 묶음 한가운데와 시각이 바뀌는 자리에 모두 온다. 4장씩은 마지막 쪽이 꼭 찬다
    for limit in (1, 4, 5):
        monkeypatch.setattr(photos_api, "PHOTO_LIST_LIMIT", limit)
        seen, before = [], None
        while True:
            page = client.get(path, params={"before": before} if before else None).json()
            got = [photo["photo_id"] for photo in page["photos"]]
            seen += got
            assert 0 < len(got) <= limit and len(seen) <= len(expected), (limit, seen)
            if not page["has_more"]:
                break
            assert len(got) == limit
            before = got[-1]
        assert seen == expected, limit
