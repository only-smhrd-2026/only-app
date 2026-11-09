"""사진 올리기 (BE-02, D17) — JPEG 로 다시 만들어 저장, 사진 보기 주소로 열림, 사진이 아니면 거절."""

import io
import zlib

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


def _upload_one(client, data: bytes, name: str, mime: str):
    signup(client)
    room_id = make_room(client)["room_id"]
    return client.post(f"/api/rooms/{room_id}/photos", files=[("files", (name, data, mime))])


def _stored(client, r) -> Image.Image:
    assert r.status_code == 201, r.text
    return Image.open(io.BytesIO(client.get(r.json()["photos"][0]["url"]).content))


def test_sideways_photo_is_turned_upright(client):
    """폰이 '옆으로 찍음'(EXIF Orientation 6)이라고 적은 40×30 사진 → 저장본은 똑바로 선 30×40."""
    exif = Image.Exif()
    exif[0x0112] = 6
    buf = io.BytesIO()
    Image.new("RGB", (40, 30), "red").save(buf, "JPEG", exif=exif.tobytes())
    assert _stored(client, _upload_one(client, buf.getvalue(), "s.jpg", "image/jpeg")).size == (30, 40)


def test_transparent_png_and_comment_are_cleaned(client):
    """투명 PNG 도 JPEG 로 저장되고, 원본 주석(위치를 글로 적어 둔 경우)은 저장본에 따라오지 않는다."""
    png = io.BytesIO()
    Image.new("RGBA", (40, 30), (255, 0, 0, 0)).save(png, "PNG")
    assert _stored(client, _upload_one(client, png.getvalue(), "t.png", "image/png")).format == "JPEG"

    commented = io.BytesIO()
    Image.new("RGB", (40, 30), "red").save(commented, "JPEG", comment=b"GPS 37.56,126.97 home")
    assert "comment" not in _stored(client, _upload_one(client, commented.getvalue(), "c.jpg", "image/jpeg")).info


def test_broken_png_is_400_not_500(client):
    """머리 부분이 깨진 PNG(Pillow 가 OSError 가 아닌 ValueError 를 냄)도 400 BAD_IMAGE."""
    good = io.BytesIO()
    Image.new("RGB", (40, 30), "red").save(good, "PNG")
    data = good.getvalue()
    broken = data[:11] + bytes([12]) + data[12:]  # IHDR 길이 13 → 12
    r = _upload_one(client, broken, "b.png", "image/png")
    assert r.status_code == 400 and r.json()["code"] == "BAD_IMAGE"


def test_png_with_broken_pixels_is_400_not_black_photo(client):
    """그림 데이터(IDAT) 가운데가 깨진 PNG — 반쯤 검은 사진으로 저장(201)하지 않고 400 으로 거절."""
    good = io.BytesIO()
    Image.linear_gradient("L").resize((128, 96)).convert("RGB").save(good, "PNG")
    data = bytearray(good.getvalue())
    i = data.index(b"IDAT")
    size = int.from_bytes(data[i - 4 : i], "big")
    data[i + 4 + size // 2] ^= 0xFF  # 압축된 그림 한가운데 1바이트를 뒤집고
    data[i + 4 + size : i + 8 + size] = zlib.crc32(bytes(data[i : i + 4 + size])).to_bytes(4, "big")  # 검사합은 맞춤
    r = _upload_one(client, bytes(data), "p.png", "image/png")
    assert r.status_code == 400 and r.json()["code"] == "BAD_IMAGE"
