"""사진 올리기 (BE-02, FR-ME-001/002/004, D17). 목록 보기·정정은 아직 stubs.py 에 있다."""

import io
import logging
import threading
import uuid
from datetime import date

from fastapi import APIRouter, File, Form, UploadFile
from PIL import ExifTags, Image, ImageOps
from pillow_heif import register_heif_opener
from sqlalchemy import select

from app.config import (
    JPEG_MAX_SCANS,
    PHOTO_MAX_SIDE,
    UPLOAD_LOCK_WAIT_SEC,
    UPLOAD_MAX_BYTES,
    UPLOAD_MAX_EXIF_BYTES,
    UPLOAD_MAX_EXIF_SEGMENTS,
    UPLOAD_MAX_FILES,
    UPLOAD_MAX_PIXELS,
    UPLOAD_MAX_SIDE,
    today_kst,
)
from app.deps import DB, CurrentUser, require_member
from app.errors import ApiError
from app.models import Photo
from app.schemas.photos import PhotoBatchOut, PhotoOut
from app.services import storage

log = logging.getLogger("app.photos")
router = APIRouter(prefix="/rooms/{room_id}/photos", tags=["photos"])
register_heif_opener()  # Image.open 이 아이폰 사진(HEIC)도 열게 — 서버가 켜질 때 한 번
ALLOWED_FORMATS = ["JPEG", "PNG", "HEIF"]  # D17
PIXELS_TOO_HIGH = f"사진 화소가 너무 높아요 ({UPLOAD_MAX_PIXELS // 10_000}만 화소까지)"  # 용량(10MB) 오류와 구분
# ponytail: 사진 변환·저장은 서버 전체에서 한 번에 한 요청 — 요청 하나가 수백 MB 를 쓴다(D9 워커 1개, 서버 2GB).
# 기다리는 요청도 스레드풀 한 칸을 차지해서 UPLOAD_LOCK_WAIT_SEC 까지만 기다린다. 느려지면 가족방별 잠금·큐로
_upload_lock = threading.Lock()


def taken_date(img: Image.Image) -> date | None:
    """폰이 적어 둔 촬영일(DateTimeOriginal). 'YYYY:MM:DD hh:mm:ss' 의 앞 10자. 없거나 이상하면 None.
    '마지막 수정일'(DateTime)은 쓰지 않는다 — 옛 사진을 스캔·편집하면 오늘 날짜가 되어 회상 대화가 틀어진다."""
    try:
        raw = img.getexif().get_ifd(ExifTags.IFD.Exif).get(ExifTags.Base.DateTimeOriginal)
        d = date.fromisoformat(str(raw)[:10].replace(":", "-"))
    except Exception:  # 날짜가 없거나 '0000:00:00' 같은 값 — 사진은 그대로 저장하고 날짜만 비운다
        return None
    return d if date(1900, 1, 1) <= d <= today_kst() else None  # 시계가 틀린 카메라의 미래·엉뚱한 날짜


def to_jpeg(data: bytes) -> tuple[bytes, date | None]:
    """그림만 꺼내 JPEG 로 새로 만든다. 원본의 EXIF(위치정보 포함)·주석은 따라오지 않는다 (D17).
    EXIF 가 사라지기 전에 촬영일만 따로 읽어 (JPEG 바이트, 촬영일) 로 돌려준다."""
    try:
        # 열기 전에 — JPEG 는 Image.open 안에서 EXIF 일부(해상도)를 벌써 푼다. 조작된 조각이 많으면 그것만으로 수백 MB
        if data.count(b"Exif\x00\x00") > UPLOAD_MAX_EXIF_SEGMENTS:
            raise ApiError(400, "BAD_IMAGE", "사진 파일을 열 수 없어요")
        # progressive JPEG 는 스캔마다 그림 전체를 다시 훑는다 — 스캔 2천 개를 붙인 222KB 사진 한 장에 CPU 25초(실측)
        # ponytail: FF DA 를 파일 전체에서 셈 — 더 촘촘히(64개) 하려면 EOI 까지 마커를 따라가며 SOS 만 세기
        if data[:2] == b"\xff\xd8" and data.count(b"\xff\xda") > JPEG_MAX_SCANS:
            raise ApiError(400, "BAD_IMAGE", "사진 파일을 열 수 없어요")
        img = Image.open(io.BytesIO(data), formats=ALLOWED_FORMATS)  # 그 밖의 형식(GIF·BMP·TIFF…)은 열지 않음
        # 그림을 풀기 전에 크기만 보고 거절 (메모리 보호). 1×3천만처럼 한 변이 아주 길면 줄 주소표만 240MB
        if img.width * img.height > UPLOAD_MAX_PIXELS or max(img.size) > UPLOAD_MAX_SIDE:
            raise ApiError(400, "IMAGE_TOO_LARGE", PIXELS_TOO_HIGH)
        img.load()  # 그림을 먼저 끝까지 푼다 — 픽셀이 깨진 파일은 여기서 오류(400). 아래 회전 단계로 넘기지 않는다
        # 촬영일·회전(EXIF)은 load 다음에 — PNG 는 getexif() 가 그림을 풀면서 깨짐 오류를 삼킬 수 있다.
        # 그림 뒤에 둔 PNG EXIF 도 load 때 읽히므로 크기도 여기서 본다
        exif = img.info.get("exif") or img.info.get("Raw profile type exif") or b""  # getexif() 가 읽는 두 곳
        taken_at = None
        if len(exif) <= UPLOAD_MAX_EXIF_BYTES:  # 조작된 큰 EXIF 는 풀면 수백 MB — 넘으면 촬영일·회전 없이 그림만 저장
            taken_at = taken_date(img)
            try:
                ImageOps.exif_transpose(img, in_place=True)  # 폰이 적어 둔 '돌려 찍음'을 실제로 돌려 둔다 (사본 없이)
            except Exception as e:  # 회전 정보(EXIF)만 깨진 사진은 돌리지 않고 그대로 저장한다
                log.warning("photo exif_transpose skipped error=%s", type(e).__name__)
        img.thumbnail((PHOTO_MAX_SIDE, PHOTO_MAX_SIDE))  # 긴 변 상한, 비율 그대로 — 저장 용량·메모리 보호 (D17)
        # 색 프로필(아이폰 사진 등) — RGB 사진일 때만 맞는 정보라 그때만 남긴다. info.clear() 전에 꺼내 둔다
        icc = img.info.get("icc_profile") if img.mode in ("RGB", "RGBA") else None
        if icc and len(icc) > UPLOAD_MAX_EXIF_BYTES:  # 조작된 큰 프로필은 버림 — 사진을 줄여도 저장본이 MB 단위가 된다
            icc = None  # 보통 프로필은 수 KB(아이폰 Display P3 약 0.5KB). EXIF 와 같은 64KB 상한을 같이 쓴다
        if img.mode in ("I;16", "I"):  # 16비트 흑백 PNG — 그대로 바꾸면 255 넘는 값이 전부 새하양
            img = img.point(lambda v: v / 256).convert("L")
        # 투명 정보: RGBA·LA 는 칸으로, P·L·RGB 는 '이 색을 투명으로'(tRNS → info["transparency"])로 들어 있다
        if img.mode in ("RGBA", "LA") or "transparency" in img.info:
            rgba = img.convert("RGBA")  # 투명한 곳은 흰 바탕 — 그냥 RGB 로 바꾸면 검게 된다
            rgb = Image.new("RGB", img.size, "white")
            rgb.paste(rgba, mask=rgba.getchannel("A"))
        else:
            rgb = img if img.mode == "RGB" else img.convert("RGB")  # 이미 RGB 면 사본을 만들지 않는다 (메모리)
        rgb.info.clear()  # 원본 주석(JPEG COM·PNG comment)이 새 JPEG 에 따라오지 않게 — 위치를 글로 적어 둔 경우가 있다
        out = io.BytesIO()
        rgb.save(out, "JPEG", quality=85, icc_profile=icc)  # 위치정보(EXIF)·주석은 남기지 않는다 (D17)
    except ApiError:
        raise  # 위에서 일부러 낸 거절(예: 픽셀 제한)은 그 코드 그대로 — 아래에서 BAD_IMAGE 로 바뀌지 않게
    except (Image.DecompressionBombError, Image.DecompressionBombWarning) as e:  # 아주 큰 그림은 Pillow 가 먼저 막는다
        raise ApiError(400, "IMAGE_TOO_LARGE", PIXELS_TOO_HIGH) from e
    except Exception as e:  # 사진이 아니거나 깨진 파일. Pillow 는 OSError 말고도 ValueError·SyntaxError 등을 낸다
        log.info("photo rejected error=%s", type(e).__name__)  # 예외 종류만 (D15)
        raise ApiError(400, "BAD_IMAGE", "사진 파일을 열 수 없어요") from e
    return out.getvalue(), taken_at


def photo_out(p: Photo) -> PhotoOut:
    return PhotoOut(
        photo_id=p.photo_id,
        url=f"/api/media/{p.object_key}",
        taken_at=p.taken_at,
        caption=p.caption,
        people_note=p.people_note,
        status=p.status,
    )


@router.post("", response_model=PhotoBatchOut, status_code=201)
def upload_photos(
    room_id: int,
    user: CurrentUser,
    db: DB,
    files: list[UploadFile] = File(
        description="JPEG/PNG/HEIC",
        json_schema_extra={"items": {"type": "string", "format": "binary"}},  # Swagger 에 [파일 선택] 버튼이 뜨게
    ),
    upload_batch_id: uuid.UUID | None = Form(None, description="같은 요청 번호로 다시 보내면 새로 저장하지 않음"),
):
    """받은 사진을 JPEG 로 다시 만들어 저장. 20장·10MB·30M 픽셀 제한, HEIC 도 받음.
    화면이 upload_batch_id 를 보내면 같은 번호의 두 번째 요청은 저장하지 않고 처음 저장본을 돌려준다 (D17)."""
    require_member(room_id, user, db)
    if len(files) > UPLOAD_MAX_FILES:
        raise ApiError(400, "TOO_MANY_PHOTOS", f"사진은 한 번에 {UPLOAD_MAX_FILES}장까지 올릴 수 있어요")
    # 그림을 풀기 전에 장당 크기부터.
    # ponytail: 요청 본문은 로그인·구성원 확인 전에 이미 다 받은 뒤다(상한은 배포 Caddy 220MB).
    # 11/12~13 사진 PR 다듬기 때 '구성원 확인 뒤 20장까지만 파싱'으로 바꾼다
    for n, f in enumerate(files, 1):
        if f.size is None or f.size > UPLOAD_MAX_BYTES:
            raise ApiError(400, "PHOTO_TOO_BIG", f"{n}번째 사진: 한 장은 {UPLOAD_MAX_BYTES // (1024 * 1024)}MB까지예요")
    # 전부 JPEG 로 바꾼 뒤에 저장소에 넣는다 — 중간에 깨진 사진이 있으면 앞 사진 파일만 남지 않게 (한 장씩 차례로, D17)
    # 한계: 저장소에 넣는 도중 고장·DB 저장 실패 때는 파일이 남을 수 있음. 막으려면 storage 에 지우기 기능 필요
    if not _upload_lock.acquire(timeout=UPLOAD_LOCK_WAIT_SEC):  # 싼 검사는 위에서 끝냄. 무거운 변환·저장만 한 요청씩
        raise ApiError(503, "UPLOAD_BUSY", "다른 사진을 올리는 중이에요. 잠시 뒤 다시 올려 주세요")
    try:
        # 같은 요청이 다시 옴(느린 인터넷에 [올리기] 두 번·재전송) — 잠금 안에서 찾아야 앞 요청의 저장이 끝난 뒤에 본다
        if upload_batch_id:
            done = db.scalars(
                select(Photo)
                .where(Photo.room_id == room_id, Photo.upload_batch_id == upload_batch_id)
                # 정렬 기준: photo_id(사진을 저장할 때 DB 가 1, 2, 3… 차례로 붙이는 번호) = 보낸 순서.
                # 그래서 두 번째 응답도 처음 응답과 사진 순서가 똑같다.
                .order_by(Photo.photo_id)
                # .order_by(Photo.object_key)
                # 제작해달라고 부탁한 방법: object_key(저장 파일 이름 …/0.jpg, …/1.jpg …) 순서.
                # 이 방법 사용하니, 파일 이름을 숫자가 아니라 글자로 비교해서
                # '10.jpg' 가 '1.jpg' 바로 뒤, '2.jpg' 앞에 온다.
                # 11장 넘게 올리면 11번째 사진이 2번째 자리로 가서 순서가 섞인다 (11/11 사진 11장으로 실측).
            ).all()
            if done:
                return PhotoBatchOut(upload_batch_id=upload_batch_id, photos=[photo_out(p) for p in done])
        converted = []
        for n, f in enumerate(files, 1):
            try:
                converted.append(to_jpeg(f.file.read()))
            except ApiError as e:  # 몇 번째 사진인지 문구 앞에 붙인다 — 응답 모양 {detail, code}·상태 코드는 그대로
                raise ApiError(e.status_code, e.code, f"{n}번째 사진: {e.detail}") from e
        batch_id = upload_batch_id or uuid.uuid4()
        photos = []
        for i, (jpeg, taken_at) in enumerate(converted):
            key = f"rooms/{room_id}/{batch_id}/{i}.jpg"
            storage.put(key, jpeg)
            photo = Photo(
                room_id=room_id,
                uploaded_by=user.user_id,
                upload_batch_id=batch_id,
                object_key=key,
                taken_at=taken_at,
                source="FAMILY",
            )
            db.add(photo)
            photos.append(photo)
        db.commit()
    finally:
        _upload_lock.release()
    return PhotoBatchOut(upload_batch_id=batch_id, photos=[photo_out(p) for p in photos])
