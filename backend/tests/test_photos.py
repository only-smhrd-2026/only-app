"""사진 올리기 (BE-02, D17) — JPEG 로 다시 만들어 저장, 사진 보기 주소로 열림, 사진이 아니면 거절."""

import io
import zlib
from datetime import date
from pathlib import Path

import pytest
from PIL import ExifTags, Image

from app.config import settings
from app.db import SessionLocal
from app.models import Photo
from app.routers import photos as photo_api
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
    with SessionLocal() as db:  # 응답만이 아니라 DB 에도 (응답은 commit 뒤 메모리 값이라 저장이 빠져도 같게 보인다)
        assert db.get(Photo, r.json()["photos"][0]["photo_id"]).taken_at == date(2019, 5, 4)

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
    assert r.json()["detail"].startswith("2번째 사진")  # 20장 중 어느 사진인지 알려 준다
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


def test_very_long_side_is_too_large(client):
    """1×3천만 PNG — 픽셀 수는 한도 안이지만 한 변이 65,500 을 넘는다 → 풀기 전에 거절 (예전엔 풀다가 BAD_IMAGE)."""
    r = _upload_one(client, _png_header(1, 30_000_000), "l.png", "image/png")
    assert r.status_code == 400 and r.json()["code"] == "IMAGE_TOO_LARGE"


def test_jpeg_with_too_many_scans_is_400(client):
    """마지막 스캔(FF DA)을 301번 덧붙인 progressive JPEG → 열기 전에 거절(스캔마다 CPU). 보통 progressive 는 통과."""
    buf = io.BytesIO()
    Image.new("RGB", (64, 64), "red").save(buf, "JPEG", progressive=True)
    j = buf.getvalue()
    assert _upload_one(client, j, "p.jpg", "image/jpeg").status_code == 201
    last_scan = j[j.rfind(b"\xff\xda") : -2]  # 끝 표시(FF D9) 앞까지
    r = _upload_one(client, j[:-2] + last_scan * 301 + j[-2:], "s.jpg", "image/jpeg")
    assert r.status_code == 400 and r.json()["code"] == "BAD_IMAGE"


def test_big_exif_is_not_read(client):
    """EXIF 가 64KB 를 넘는 PNG(조작된 EXIF 는 풀면 수백 MB) → 사진은 저장하고 촬영일·회전은 읽지 않는다."""
    exif = Image.Exif()
    ifd = exif.get_ifd(ExifTags.IFD.Exif)
    ifd[ExifTags.Base.DateTimeOriginal] = "2019:05:04 10:30:00"
    ifd[ExifTags.Base.UserComment] = b"\0" * 100_000
    buf = io.BytesIO()
    Image.new("RGB", (40, 30), "red").save(buf, "PNG", exif=exif.tobytes())
    r = _upload_one(client, buf.getvalue(), "x.png", "image/png")
    assert r.status_code == 201 and r.json()["photos"][0]["taken_at"] is None


def test_many_exif_segments_is_400(client):
    """EXIF 조각이 5개 이상인 JPEG → 열기 전에 거절 (JPEG 는 여는 단계에서 EXIF 를 푼다). 4개까지는 통과."""
    t = Image.Exif().tobytes()  # b"Exif\0\0" 로 시작
    app1 = b"\xff\xe1" + (len(t) + 2).to_bytes(2, "big") + t
    data = _jpeg()
    assert _upload_one(client, data[:2] + app1 * 4 + data[2:], "e4.jpg", "image/jpeg").status_code == 201
    r = _upload_one(client, data[:2] + app1 * 5 + data[2:], "e5.jpg", "image/jpeg")
    assert r.status_code == 400 and r.json()["code"] == "BAD_IMAGE"


def test_big_photo_is_shrunk_to_2560(client):
    """긴 변이 2560 을 넘으면 비율 그대로 줄여 저장 (저장 용량·메모리 보호). 작은 사진은 그대로(여러 장 테스트)."""
    buf = io.BytesIO()
    Image.new("RGB", (6000, 4000), "red").save(buf, "JPEG")
    assert _stored(client, _upload_one(client, buf.getvalue(), "w.jpg", "image/jpeg")).size == (2560, 1707)


def test_busy_upload_is_503_then_ok(client, monkeypatch):
    """다른 요청이 사진을 바꾸는 중(잠금)이면 기다리다 503 UPLOAD_BUSY. 잠금이 풀리면 올라간다.
    요청은 서버 쪽 다른 스레드에서 돈다 — 테스트가 잠금을 쥐고 있으면 그 스레드는 잡지 못한다."""
    monkeypatch.setattr(photo_api, "UPLOAD_LOCK_WAIT_SEC", 0.1)
    signup(client)
    room_id = make_room(client)["room_id"]
    files = [("files", ("a.jpg", _jpeg(), "image/jpeg"))]
    with photo_api._upload_lock:
        r = client.post(f"/api/rooms/{room_id}/photos", files=files)
    assert r.status_code == 503 and r.json()["code"] == "UPLOAD_BUSY"
    assert client.post(f"/api/rooms/{room_id}/photos", files=files).status_code == 201


def test_photos_keep_order_and_dates(client):
    """여러 장을 한 번에 → 보낸 순서대로 저장되고, 촬영일이 제 사진에 붙는다."""
    dated = _jpeg_with_exif(
        lambda e: e.get_ifd(ExifTags.IFD.Exif).__setitem__(ExifTags.Base.DateTimeOriginal, "2019:05:04 10:30:00")
    )
    png, wide = io.BytesIO(), io.BytesIO()
    Image.new("RGB", (50, 20)).save(png, "PNG")
    Image.new("RGB", (60, 10)).save(wide, "JPEG")
    signup(client)
    room_id = make_room(client)["room_id"]
    files = [
        ("files", ("a.jpg", dated, "image/jpeg")),
        ("files", ("b.png", png.getvalue(), "image/png")),
        ("files", ("c.jpg", wide.getvalue(), "image/jpeg")),
    ]
    r = client.post(f"/api/rooms/{room_id}/photos", files=files)
    assert r.status_code == 201, r.text
    photos = r.json()["photos"]
    assert [p["taken_at"] for p in photos] == ["2019-05-04", None, None]
    sizes = [Image.open(io.BytesIO(client.get(p["url"]).content)).size for p in photos]
    assert sizes == [(40, 30), (50, 20), (60, 10)]


def test_20_photos_is_ok(client):
    signup(client)
    room_id = make_room(client)["room_id"]
    files = [("files", (f"{i}.jpg", _jpeg(), "image/jpeg")) for i in range(20)]
    r = client.post(f"/api/rooms/{room_id}/photos", files=files)
    assert r.status_code == 201 and len(r.json()["photos"]) == 20


def test_exactly_30m_pixels_passes_pixel_check(client):
    """정확히 3천만 픽셀은 픽셀 검사를 통과한다(그림 내용이 없어 BAD_IMAGE). 1줄 더 많으면 IMAGE_TOO_LARGE."""
    assert _upload_one(client, _png_header(6000, 5000), "e.png", "image/png").json()["code"] == "BAD_IMAGE"
    assert _upload_one(client, _png_header(6000, 5001), "e.png", "image/png").json()["code"] == "IMAGE_TOO_LARGE"


@pytest.mark.parametrize("raw", ["0000:00:00 00:00:00", "1899:12:31 23:59:59"])
def test_odd_taken_date_is_dropped(client, raw):
    """'0000:00:00'(날짜를 모르는 카메라)·1900년 이전 → 사진은 저장하고 촬영일만 비운다."""
    data = _jpeg_with_exif(lambda e: e.get_ifd(ExifTags.IFD.Exif).__setitem__(ExifTags.Base.DateTimeOriginal, raw))
    r = _upload_one(client, data, "o.jpg", "image/jpeg")
    assert r.status_code == 201 and r.json()["photos"][0]["taken_at"] is None
