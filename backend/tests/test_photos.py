"""사진 올리기 (BE-02, D17) — JPEG 로 다시 만들어 저장, 사진 보기 주소로 열림, 사진이 아니면 거절."""

import io

from PIL import Image

from tests.conftest import make_room, signup


def _jpeg() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (40, 30), "red").save(buf, "JPEG")
    return buf.getvalue()


def test_upload_one_jpeg_then_view(client):
    signup(client)
    room_id = make_room(client)["room_id"]
    r = client.post(f"/api/rooms/{room_id}/photos", files=[("files", ("a.jpg", _jpeg(), "image/jpeg"))])
    assert r.status_code == 201, r.text
    photos = r.json()["photos"]
    assert len(photos) == 1 and photos[0]["status"] == "ACTIVE"

    m = client.get(photos[0]["url"])
    assert m.status_code == 200 and m.headers["content-type"] == "image/jpeg"
    assert Image.open(io.BytesIO(m.content)).format == "JPEG"


def test_not_an_image_is_rejected(client):
    signup(client)
    room_id = make_room(client)["room_id"]
    r = client.post(f"/api/rooms/{room_id}/photos", files=[("files", ("x.jpg", b"not an image", "image/jpeg"))])
    assert r.status_code == 400 and r.json()["code"] == "BAD_IMAGE"


def test_gif_is_rejected(client):
    """D17 허용 형식(JPEG/PNG/HEIC) 밖이면 진짜 그림 파일이어도 거절."""
    signup(client)
    room_id = make_room(client)["room_id"]
    buf = io.BytesIO()
    Image.new("RGB", (40, 30), "red").save(buf, "GIF")
    r = client.post(f"/api/rooms/{room_id}/photos", files=[("files", ("a.gif", buf.getvalue(), "image/gif"))])
    assert r.status_code == 400 and r.json()["code"] == "BAD_IMAGE"
