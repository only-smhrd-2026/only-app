"""사진 올리기 (BE-02, D17) — JPEG 로 다시 만들어 저장, 사진 보기 주소로 열림, 사진이 아니면 거절."""

import io
import zlib
from pathlib import Path

from PIL import ExifTags, Image

from app.config import settings
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


def test_more_than_20_photos_is_400(client):
    signup(client)
    room_id = make_room(client)["room_id"]
    files = [("files", (f"{i}.jpg", _jpeg(), "image/jpeg")) for i in range(21)]
    r = client.post(f"/api/rooms/{room_id}/photos", files=files)
    assert r.status_code == 400 and r.json()["code"] == "TOO_MANY_PHOTOS"


def test_photo_over_10mb_is_400(client):
    big = b"\0" * (10 * 1024 * 1024 + 1)
    r = _upload_one(client, big, "big.jpg", "image/jpeg")
    assert r.status_code == 400 and r.json()["code"] == "PHOTO_TOO_BIG"


def test_photo_over_30m_pixels_is_400(client):
    """6000×6000 = 3,600만 픽셀. 파일은 작아도(한 가지 색) 풀면 메모리를 많이 쓰므로 거절."""
    buf = io.BytesIO()
    Image.new("RGB", (6000, 6000), "red").save(buf, "JPEG")
    assert len(buf.getvalue()) < 10 * 1024 * 1024  # 10MB 검사가 아니라 픽셀 검사에서 막히는지 보려고
    r = _upload_one(client, buf.getvalue(), "huge.jpg", "image/jpeg")
    assert r.status_code == 400 and r.json()["code"] == "IMAGE_TOO_LARGE"


def test_taken_date_is_saved(client):
    """폰처럼 Exif 칸에 촬영일(DateTimeOriginal)을 적은 JPEG → 응답 taken_at 이 그 날짜. 날짜 없는 사진은 None."""
    exif = Image.Exif()
    exif.get_ifd(ExifTags.IFD.Exif)[ExifTags.Base.DateTimeOriginal] = "2019:05:04 10:30:00"
    buf = io.BytesIO()
    Image.new("RGB", (40, 30), "red").save(buf, "JPEG", exif=exif.tobytes())
    r = _upload_one(client, buf.getvalue(), "d.jpg", "image/jpeg")
    assert r.status_code == 201 and r.json()["photos"][0]["taken_at"] == "2019-05-04"

    assert _upload_one(client, _jpeg(), "n.jpg", "image/jpeg").json()["photos"][0]["taken_at"] is None


def _jpeg_with_exif(fill) -> bytes:
    exif = Image.Exif()
    fill(exif)
    buf = io.BytesIO()
    Image.new("RGB", (40, 30), "red").save(buf, "JPEG", exif=exif.tobytes())
    return buf.getvalue()


def test_modified_date_is_not_taken_date(client):
    """'마지막 수정일'(DateTime)만 있는 사진(옛 사진을 스캔·편집한 경우) → 촬영일로 쓰지 않는다."""
    data = _jpeg_with_exif(lambda e: e.__setitem__(ExifTags.Base.DateTime, "2026:11:10 09:00:00"))
    assert _upload_one(client, data, "m.jpg", "image/jpeg").json()["photos"][0]["taken_at"] is None


def test_future_taken_date_is_dropped(client):
    """시계가 틀린 카메라의 미래 날짜 → 비워 둔다."""

    def fill(e):
        e.get_ifd(ExifTags.IFD.Exif)[ExifTags.Base.DateTimeOriginal] = "2099:01:01 00:00:00"

    data = _jpeg_with_exif(fill)
    assert _upload_one(client, data, "f.jpg", "image/jpeg").json()["photos"][0]["taken_at"] is None


def _png_header(w: int, h: int) -> bytes:
    """크기만 적은 PNG (그림 내용 없음). Pillow 가 여는 단계에서 크기를 읽는다."""

    def chunk(t: bytes, d: bytes) -> bytes:
        return len(d).to_bytes(4, "big") + t + d + zlib.crc32(t + d).to_bytes(4, "big")

    ihdr = w.to_bytes(4, "big") + h.to_bytes(4, "big") + bytes([8, 0, 0, 0, 0])
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", zlib.compress(b"")) + chunk(b"IEND", b"")


def test_huge_png_is_too_large_not_bad_image(client):
    """2억 2500만 픽셀 → Pillow 가 먼저 막아도 '열 수 없어요'가 아니라 '너무 커요'(IMAGE_TOO_LARGE)."""
    r = _upload_one(client, _png_header(15000, 15000), "h.png", "image/png")
    assert r.status_code == 400 and r.json()["code"] == "IMAGE_TOO_LARGE"


def test_broken_photo_in_batch_leaves_no_file(client):
    """2장 중 둘째가 깨진 사진 → 400 이고, 첫째 사진 파일도 저장소에 남지 않는다 (DB 에 없는 파일이 쌓이지 않게)."""
    signup(client)
    room_id = make_room(client)["room_id"]
    room_dir = Path(settings.UPLOAD_DIR) / "rooms" / str(room_id)
    before = set(room_dir.rglob("*.jpg"))
    files = [("files", ("a.jpg", _jpeg(), "image/jpeg")), ("files", ("b.jpg", b"broken", "image/jpeg"))]
    r = client.post(f"/api/rooms/{room_id}/photos", files=files)
    assert r.status_code == 400 and r.json()["code"] == "BAD_IMAGE"
    assert set(room_dir.rglob("*.jpg")) == before


def test_gps_is_removed(client):
    """위치정보(GPS)를 적은 JPEG → 저장본 EXIF 에 GPS 가 없다 (D17)."""
    exif = Image.Exif()
    exif.get_ifd(ExifTags.IFD.GPSInfo)[ExifTags.GPS.GPSLatitudeRef] = "N"
    buf = io.BytesIO()
    Image.new("RGB", (40, 30), "red").save(buf, "JPEG", exif=exif.tobytes())
    assert Image.open(io.BytesIO(buf.getvalue())).getexif().get_ifd(ExifTags.IFD.GPSInfo)  # 원본에는 GPS 가 있다

    stored = _stored(client, _upload_one(client, buf.getvalue(), "g.jpg", "image/jpeg"))
    assert not stored.getexif().get_ifd(ExifTags.IFD.GPSInfo)
