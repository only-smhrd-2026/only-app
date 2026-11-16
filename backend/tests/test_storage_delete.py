"""파일 삭제의 반복 실행·없는 파일·잘못된 키 차단을 확인한다."""

import uuid

import pytest

from app.services import storage


def test_local_delete_is_idempotent():
    key = f"rooms/1/{uuid.uuid4()}/0.jpg"
    storage.put(key, b"test image")
    assert storage.get(key) is not None
    storage.delete(key)
    storage.delete(key)
    assert storage.get(key) is None


@pytest.mark.parametrize("key", ["", "../outside.jpg", "/absolute.jpg", "rooms/1/not-a-uuid/0.jpg"])
def test_invalid_key_is_rejected_before_backend_access(key, monkeypatch):
    monkeypatch.setattr(storage, "_get_backend", lambda: pytest.fail("잘못된 키로 저장소에 접근하면 안 됩니다"))
    with pytest.raises(ValueError):
        storage.delete(key)
