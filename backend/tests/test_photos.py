"""사진 올리기 (BE-02, D17) — JPEG 로 다시 만들어 저장, 사진 보기 주소로 열림, 사진이 아니면 거절."""

import io
import uuid
import zlib
from datetime import date
from pathlib import Path

import pillow_heif
import pytest
from PIL import ExifTags, Image, ImageCms
from sqlalchemy import func, select

from app.config import PHOTO_LIST_LIMIT, UPLOAD_MAX_ICC_BYTES, settings
from app.db import SessionLocal, engine
from app.models import Photo
from app.routers import photos as photo_api
from tests.conftest import add_photos, connect_device, make_room, signup


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
    """D17 허용 형식(JPEG/PNG) 밖이면 진짜 그림 파일이어도 거절."""
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


def test_heic_is_rejected(client):
    """아이폰 사진(HEIC)은 지금 받지 않는다 → 400 BAD_IMAGE. 조작된 HEIC 는 열기만 해도 1~2GB (ALLOWED_FORMATS 주석)."""
    buf = io.BytesIO()
    pillow_heif.from_pillow(Image.new("RGB", (40, 30), "red")).save(buf)  # Pillow 에 HEIC 여는 기능을 켜지 않고 만든다
    r = _upload_one(client, buf.getvalue(), "a.heic", "image/heic")
    assert r.status_code == 400 and r.json()["code"] == "BAD_IMAGE"


def test_16bit_gray_png_is_not_white(client):
    """16비트 흑백 PNG(값 30000) — 그대로 RGB 로 바꾸면 새하양(255). 256 으로 나눠 회색(117)이 되어야 한다."""
    buf = io.BytesIO()
    Image.new("I;16", (40, 30), 30000).save(buf, "PNG")
    pixel = _stored(client, _upload_one(client, buf.getvalue(), "g.png", "image/png")).getpixel((20, 15))
    assert pixel != (255, 255, 255) and abs(pixel[0] - 117) <= 3  # JPEG 라 값이 조금 흔들림


def test_transparent_png_gets_white_background(client):
    """투명 PNG(RGBA·팔레트·'이 색을 투명으로'(tRNS) 쓰는 흑백·컬러) — 투명했던 곳은 검정이 아니라 흰색."""
    rgba = io.BytesIO()
    Image.new("RGBA", (40, 30), (0, 0, 0, 0)).save(rgba, "PNG")
    pal = Image.new("P", (40, 30), 0)
    pal.putpalette([0, 0, 0])
    p = io.BytesIO()
    pal.save(p, "PNG", transparency=0)
    gray, color = io.BytesIO(), io.BytesIO()  # 11/11 /code-review 재현: 이 두 가지가 검정으로 저장됐다
    Image.new("L", (40, 30), 0).save(gray, "PNG", transparency=0)
    Image.new("RGB", (40, 30), (0, 0, 0)).save(color, "PNG", transparency=(0, 0, 0))
    for data in (rgba.getvalue(), p.getvalue(), gray.getvalue(), color.getvalue()):
        assert _stored(client, _upload_one(client, data, "t.png", "image/png")).getpixel((20, 15)) == (255, 255, 255)


def test_color_profile_is_kept(client):
    """색 프로필(ICC)이 있는 사진 → 저장본에도 같은 색 프로필. 위치정보(EXIF)는 test_gps_is_removed 가 본다."""
    icc = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()
    buf = io.BytesIO()
    Image.new("RGB", (40, 30), "red").save(buf, "JPEG", icc_profile=icc)
    assert _stored(client, _upload_one(client, buf.getvalue(), "c.jpg", "image/jpeg")).info.get("icc_profile") == icc


def test_huge_color_profile_is_dropped(client):
    """색 프로필이 64KB 넘으면 버린다 — 9MB 짜리를 붙이면 작은 사진도 저장본이 9MB 가 됐다 (11/11 /code-review 재현).
    아이폰 Display P3 프로필은 약 0.5KB 라 영향 없음."""
    icc = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes() + b"A" * (UPLOAD_MAX_ICC_BYTES + 1)
    buf = io.BytesIO()
    Image.new("RGB", (40, 30), "red").save(buf, "JPEG", icc_profile=icc)
    r = _upload_one(client, buf.getvalue(), "c.jpg", "image/jpeg")
    assert "icc_profile" not in _stored(client, r).info
    assert len(client.get(r.json()["photos"][0]["url"]).content) < 64 * 1024


def test_gray_color_profile_on_color_photo_is_dropped(client):
    """컬러(RGB) 사진에 흑백(GRAY) 색 프로필 → 저장본에 붙이지 않는다. RGB 프로필(sRGB)은 test_color_profile_is_kept."""
    srgb = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()
    gray = srgb[:16] + b"GRAY" + srgb[20:]  # 머리의 색 공간 칸(16~19바이트)만 흑백으로
    buf = io.BytesIO()
    Image.new("RGB", (40, 30), "red").save(buf, "JPEG", icc_profile=gray)
    assert Image.open(io.BytesIO(buf.getvalue())).info["icc_profile"] == gray  # 원본에는 흑백 프로필이 있다
    assert "icc_profile" not in _stored(client, _upload_one(client, buf.getvalue(), "g.jpg", "image/jpeg")).info


def _batch_count(batch_id: str) -> int:
    with SessionLocal() as db:
        return db.scalar(select(func.count()).select_from(Photo).where(Photo.upload_batch_id == uuid.UUID(batch_id)))


def test_same_batch_id_is_saved_once(client):
    """같은 upload_batch_id 로 2장을 두 번 → 두 번 다 201, DB 에는 2장(4장 아님), 두 응답의 photo_id 가 같다."""
    signup(client)
    room_id = make_room(client)["room_id"]
    files = [("files", (f"{i}.jpg", _jpeg(), "image/jpeg")) for i in range(2)]
    batch = str(uuid.uuid4())  # DB 는 테스트마다 비우지 않아서 테스트마다 새 번호
    r1 = client.post(f"/api/rooms/{room_id}/photos", files=files, data={"upload_batch_id": batch})
    r2 = client.post(f"/api/rooms/{room_id}/photos", files=files, data={"upload_batch_id": batch})
    assert r1.status_code == 201 and r2.status_code == 201
    assert _batch_count(batch) == 2
    assert [p["photo_id"] for p in r1.json()["photos"]] == [p["photo_id"] for p in r2.json()["photos"]]
    assert r2.json()["upload_batch_id"] == batch


def test_same_batch_id_keeps_order_over_10_photos(client):
    """11장을 같은 번호로 두 번 → 두 번째 응답도 보낸 순서 그대로.
    파일 이름(object_key) 순서로 바꾸면 '10.jpg' 가 '2.jpg' 앞에 와서 이 테스트가 실패한다 (11/11 실측)."""
    signup(client)
    room_id = make_room(client)["room_id"]
    files = [("files", (f"{i}.jpg", _jpeg(), "image/jpeg")) for i in range(11)]
    batch = str(uuid.uuid4())
    r1 = client.post(f"/api/rooms/{room_id}/photos", files=files, data={"upload_batch_id": batch})
    r2 = client.post(f"/api/rooms/{room_id}/photos", files=files, data={"upload_batch_id": batch})
    assert r1.status_code == 201 and r2.status_code == 201  # 실패 응답이면 KeyError 대신 상태 코드로 알려 준다
    assert [p["photo_id"] for p in r2.json()["photos"]] == [p["photo_id"] for p in r1.json()["photos"]]


def test_no_batch_id_saves_twice(client):
    """upload_batch_id 없이 두 번 보내면 따로 두 번 저장된다 (지금까지와 같음)."""
    signup(client)
    room_id = make_room(client)["room_id"]
    files = [("files", ("a.jpg", _jpeg(), "image/jpeg"))]
    r1 = client.post(f"/api/rooms/{room_id}/photos", files=files)
    r2 = client.post(f"/api/rooms/{room_id}/photos", files=files)
    assert r1.status_code == 201 and r2.status_code == 201
    assert r1.json()["upload_batch_id"] != r2.json()["upload_batch_id"]
    assert r1.json()["photos"][0]["photo_id"] != r2.json()["photos"][0]["photo_id"]


def test_login_and_member_checked_before_body_is_read(client, monkeypatch):
    """로그인 안 함(401)·남의 가족방(404)은 사진 본문(최대 220MB)을 읽기 전에 끝난다. 구성원이면 그때 읽는다."""
    from starlette import formparsers

    parsed, orig = [], formparsers.MultiPartParser.parse

    async def spy(self):
        parsed.append(1)
        return await orig(self)

    monkeypatch.setattr(formparsers.MultiPartParser, "parse", spy)
    files = [("files", ("a.jpg", _jpeg(), "image/jpeg"))]
    assert client.post("/api/rooms/1/photos", files=files).status_code == 401
    signup(client)
    room_id = make_room(client)["room_id"]
    assert client.post(f"/api/rooms/{room_id + 999}/photos", files=files).status_code == 404
    assert parsed == []
    assert client.post(f"/api/rooms/{room_id}/photos", files=files).status_code == 201 and parsed == [1]


def test_waiting_for_lock_holds_no_db_connection(client, monkeypatch):
    """잠금을 기다리는 동안(최대 60초) DB 연결을 쥐지 않는다 — 15명이 기다리면 연결(5+10개)이 바닥나 다른 화면도 멈춘다.
    db.close() 를 빼면 [1]."""
    seen = []

    class SpyLock:
        def acquire(self, timeout):
            seen.append(engine.pool.checkedout())
            return True

        def release(self):
            pass

    monkeypatch.setattr(photo_api, "_upload_lock", SpyLock())
    signup(client)
    room_id = make_room(client)["room_id"]
    r = client.post(f"/api/rooms/{room_id}/photos", files=[("files", ("a.jpg", _jpeg(), "image/jpeg"))])
    assert r.status_code == 201 and seen == [0]


def test_cut_upload_is_400_not_500(client, monkeypatch):
    """폰이 올리는 도중 끊김(ClientDisconnect) → 서버 오류(500)가 아니라 400 UPLOAD_CUT."""
    from starlette import formparsers
    from starlette.requests import ClientDisconnect

    async def cut(self):
        raise ClientDisconnect()

    monkeypatch.setattr(formparsers.MultiPartParser, "parse", cut)
    r = _upload_one(client, _jpeg(), "a.jpg", "image/jpeg")
    assert r.status_code == 400 and r.json()["code"] == "UPLOAD_CUT"


def test_blank_batch_id_is_none_and_bad_one_is_422(client):
    """upload_batch_id 빈 칸은 번호 없음(201), uuid 가 아니면 422. 사진 없이 보내도 422."""
    signup(client)
    url = f"/api/rooms/{make_room(client)['room_id']}/photos"
    files = [("files", ("a.jpg", _jpeg(), "image/jpeg"))]
    assert client.post(url, files=files, data={"upload_batch_id": ""}).status_code == 201
    r = client.post(url, files=files, data={"upload_batch_id": "not-a-uuid"})
    assert r.status_code == 422 and r.json()["code"] == "VALIDATION"
    r = client.post(url, data={"upload_batch_id": str(uuid.uuid4())})
    assert r.status_code == 422 and r.json()["code"] == "VALIDATION"


# ---------------------------------------------------------------- 한마디·사진 속 사람 (FR-ME-002, D17)
def test_caption_and_people_note_saved_on_every_photo(client):
    """JPEG 2장 + 한마디 + 사진 속 사람 → 두 사진 모두 같은 글. 사진 목록(GET)에도 같은 글."""
    signup(client)
    room_id = make_room(client)["room_id"]
    files = [("files", (f"{i}.jpg", _jpeg(), "image/jpeg")) for i in range(2)]
    data = {"upload_batch_id": str(uuid.uuid4()), "caption": "설날 온 가족이 모인 날", "people_note": "할머니, 큰딸"}
    r = client.post(f"/api/rooms/{room_id}/photos", files=files, data=data)
    assert r.status_code == 201, r.text
    for photos in (r.json()["photos"], _list(client, room_id)):
        assert len(photos) == 2
        assert all(p["caption"] == "설날 온 가족이 모인 날" and p["people_note"] == "할머니, 큰딸" for p in photos)


@pytest.mark.parametrize("extra", [{}, {"caption": "", "people_note": ""}, {"caption": "   ", "people_note": "   "}])
def test_missing_or_blank_note_is_none(client, extra):
    """두 칸이 없거나, 빈 칸이거나, 공백만이면 None."""
    signup(client)
    room_id = make_room(client)["room_id"]
    files = [("files", ("a.jpg", _jpeg(), "image/jpeg"))]
    r = client.post(f"/api/rooms/{room_id}/photos", files=files, data={"upload_batch_id": str(uuid.uuid4()), **extra})
    assert r.status_code == 201, r.text
    assert r.json()["photos"][0]["caption"] is None and r.json()["photos"][0]["people_note"] is None


def test_note_over_100_chars_is_422_and_saves_nothing(client):
    """100자는 201, 101자는 422 VALIDATION 이고 그 번호로 저장된 사진은 0장. 글 칸에 파일이 와도 422."""
    signup(client)
    url = f"/api/rooms/{make_room(client)['room_id']}/photos"
    files = [("files", ("a.jpg", _jpeg(), "image/jpeg"))]
    ok = client.post(url, files=files, data={"upload_batch_id": str(uuid.uuid4()), "caption": "가" * 100})
    assert ok.status_code == 201 and ok.json()["photos"][0]["caption"] == "가" * 100
    for name, msg in (("caption", "한마디는 100자까지"), ("people_note", "사진 속 사람은 100자까지")):
        batch = str(uuid.uuid4())
        r = client.post(url, files=files, data={"upload_batch_id": batch, name: "가" * 101})
        assert r.status_code == 422 and r.json()["code"] == "VALIDATION" and msg in r.json()["detail"]
        assert _batch_count(batch) == 0
    batch = str(uuid.uuid4())
    as_file = files + [("caption", ("c.txt", b"hello", "text/plain"))]
    r = client.post(url, files=as_file, data={"upload_batch_id": batch})
    assert r.status_code == 422 and r.json()["code"] == "VALIDATION" and _batch_count(batch) == 0


@pytest.mark.parametrize("name", ["caption", "people_note"])
def test_nul_in_note_is_422_and_leaves_no_file(client, name):
    """글에 NUL(\\x00)이 있으면 422 — DB(PostgreSQL)가 저장을 거부해 500 이 나고 사진 파일만 남던 것 (11/13 리뷰)."""
    signup(client)
    room_id = make_room(client)["room_id"]
    batch = str(uuid.uuid4())
    files = [("files", (f"{i}.jpg", _jpeg(), "image/jpeg")) for i in range(2)]
    r = client.post(f"/api/rooms/{room_id}/photos", files=files, data={"upload_batch_id": batch, name: "a\x00b"})
    assert r.status_code == 422 and r.json()["code"] == "VALIDATION"
    assert _batch_count(batch) == 0
    assert not (Path(settings.UPLOAD_DIR) / "rooms" / str(room_id) / batch).exists()


def test_same_batch_id_keeps_first_caption(client):
    """같은 upload_batch_id 로 한마디만 바꿔 다시 보내면 201 이고 처음 한마디 그대로, 사진 수도 그대로 (D17)."""
    signup(client)
    room_id = make_room(client)["room_id"]
    files = [("files", (f"{i}.jpg", _jpeg(), "image/jpeg")) for i in range(2)]
    batch = str(uuid.uuid4())
    r1 = client.post(f"/api/rooms/{room_id}/photos", files=files, data={"upload_batch_id": batch, "caption": "처음 글"})
    r2 = client.post(f"/api/rooms/{room_id}/photos", files=files, data={"upload_batch_id": batch, "caption": "다른 글"})
    assert r1.status_code == 201 and r2.status_code == 201
    assert [p["caption"] for p in r2.json()["photos"]] == ["처음 글", "처음 글"]
    assert _batch_count(batch) == 2


def test_four_text_fields_is_400(client):
    """글 칸은 upload_batch_id·caption·people_note 셋까지. 모르는 칸 하나를 더 보내면 400."""
    signup(client)
    url = f"/api/rooms/{make_room(client)['room_id']}/photos"
    data = {"upload_batch_id": str(uuid.uuid4()), "caption": "a", "people_note": "b", "unknown": "c"}
    assert client.post(url, files=[("files", ("a.jpg", _jpeg(), "image/jpeg"))], data=data).status_code == 400


# ---------------------------------------------------------------- 사진 목록 (GET, FR-ME-004)
def _list(client, room_id: int) -> list[dict]:
    r = client.get(f"/api/rooms/{room_id}/photos")
    assert r.status_code == 200, r.text
    return r.json()["photos"]


def test_list_newest_first(client):
    """1장 → 2장 올리면 목록 3장. 나중에 올린 2장이 앞, 같은 요청 안에서는 photo_id 큰 것이 앞."""
    signup(client)
    room_id = make_room(client)["room_id"]
    url = f"/api/rooms/{room_id}/photos"
    first = client.post(url, files=[("files", ("a.jpg", _jpeg(), "image/jpeg"))]).json()["photos"]
    files = [("files", (f"{i}.jpg", _jpeg(), "image/jpeg")) for i in range(2)]
    second = client.post(url, files=files).json()["photos"]
    ids = [p["photo_id"] for p in _list(client, room_id)]
    assert ids == [second[1]["photo_id"], second[0]["photo_id"], first[0]["photo_id"]]


def test_list_hides_deleted_photo(client):
    """지운 사진(DELETED)은 목록에 없다."""
    signup(client)
    room_id = make_room(client)["room_id"]
    files = [("files", (f"{i}.jpg", _jpeg(), "image/jpeg")) for i in range(2)]
    kept, gone = client.post(f"/api/rooms/{room_id}/photos", files=files).json()["photos"]
    with SessionLocal() as db:
        db.get(Photo, gone["photo_id"]).status = "DELETED"
        db.commit()
    assert [p["photo_id"] for p in _list(client, room_id)] == [kept["photo_id"]]


def test_list_needs_login_and_membership(client):
    """로그인 안 함 401, 남의 가족방 404 ROOM_NOT_FOUND (있는지도 모르게)."""
    assert client.get("/api/rooms/1/photos").status_code == 401
    signup(client)
    room_id = make_room(client)["room_id"]
    r = client.get(f"/api/rooms/{room_id + 999}/photos")
    assert r.status_code == 404 and r.json()["code"] == "ROOM_NOT_FOUND"
    signup(client)  # 다른 가족 — 방은 있지만 구성원이 아니다. 없는 방과 똑같이 404
    r = client.get(f"/api/rooms/{room_id}/photos")
    assert r.status_code == 404 and r.json()["code"] == "ROOM_NOT_FOUND"


def test_list_shows_elder_camera_but_not_diary_photo(client):
    """가족 사진 목록에는 어르신 카메라(ELDER_CAMERA)도 보이고 그림일기(FAMILY_DIARY)는 빠짐.
    어르신 사진첩(album)은 11/13 부터 가족이 올린 사진만이다 (D60)."""
    signup(client)
    room_id = make_room(client)["room_id"]
    files = [("files", (f"{i}.jpg", _jpeg(), "image/jpeg")) for i in range(2)]
    camera, diary = client.post(f"/api/rooms/{room_id}/photos", files=files).json()["photos"]
    with SessionLocal() as db:
        db.get(Photo, camera["photo_id"]).source = "ELDER_CAMERA"
        db.get(Photo, diary["photo_id"]).source = "FAMILY_DIARY"
        db.commit()
    assert [p["photo_id"] for p in _list(client, room_id)] == [camera["photo_id"]]


def test_list_empty_room(client):
    signup(client)
    assert _list(client, make_room(client)["room_id"]) == []


def test_list_same_batch_twice_is_3(client):
    """이슈 #10 다 됐다: 같은 upload_batch_id 로 JPEG 3장을 두 번 보내도 목록은 3장."""
    signup(client)
    room_id = make_room(client)["room_id"]
    files = [("files", (f"{i}.jpg", _jpeg(), "image/jpeg")) for i in range(3)]
    batch = str(uuid.uuid4())
    for _ in range(2):
        r = client.post(f"/api/rooms/{room_id}/photos", files=files, data={"upload_batch_id": batch})
        assert r.status_code == 201
    assert len(_list(client, room_id)) == 3


def test_list_same_as_elder_album(client):
    """가족이 올린 사진은 가족 사진 목록과 어르신 사진첩에서 같은 순서·상한(PHOTO_LIST_LIMIT) — 한쪽만 바꾸면 걸린다."""
    signup(client)
    room_id = make_room(client)["room_id"]
    client.post(f"/api/rooms/{room_id}/photos", files=[("files", ("a.jpg", _jpeg(), "image/jpeg"))])
    add_photos(room_id, PHOTO_LIST_LIMIT)  # 번호는 더 크지만 하루 전에 올린 사진 → 모두 상한 + 1장
    connect_device(client, room_id)
    album = [p["photo_id"] for p in client.get("/api/elder/album").json()["photos"]]
    listed = [p["photo_id"] for p in _list(client, room_id)]
    assert listed == album and len(album) == PHOTO_LIST_LIMIT
    assert listed[0] == min(listed)  # 방금 올린 사진(번호는 가장 작음)이 맨 앞 — 올린 시각이 번호보다 먼저
