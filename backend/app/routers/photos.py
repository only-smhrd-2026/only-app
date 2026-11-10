"""사진 올리기 (BE-02, FR-ME-001/002/004, D17). 목록 보기·정정은 아직 stubs.py 에 있다."""

import io
import logging
import uuid
from datetime import date

from fastapi import APIRouter, File, UploadFile
from PIL import ExifTags, Image, ImageOps

from app.config import UPLOAD_MAX_BYTES, UPLOAD_MAX_FILES, UPLOAD_MAX_PIXELS, today_kst
from app.deps import DB, CurrentUser, require_member
from app.errors import ApiError
from app.models import Photo
from app.schemas.photos import PhotoBatchOut, PhotoOut
from app.services import storage

log = logging.getLogger("app.photos")
router = APIRouter(prefix="/rooms/{room_id}/photos", tags=["photos"])
ALLOWED_FORMATS = ["JPEG", "PNG"]  # D17. HEIC 는 pillow-heif 를 켜는 날(11/12) "HEIF" 추가


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
        img = Image.open(io.BytesIO(data), formats=ALLOWED_FORMATS)  # 그 밖의 형식(GIF·BMP·TIFF…)은 열지 않음
        if img.width * img.height > UPLOAD_MAX_PIXELS:  # 그림을 풀기 전에 크기만 보고 거절 (메모리 보호)
            raise ApiError(400, "IMAGE_TOO_LARGE", "사진이 너무 커요")
        img.load()  # 그림을 먼저 끝까지 푼다 — 픽셀이 깨진 파일은 여기서 오류(400). 아래 회전 단계로 넘기지 않는다
        taken_at = taken_date(img)  # load 다음에 — PNG 는 getexif() 가 그림을 풀면서 깨짐 오류를 삼킬 수 있다
        try:
            img = ImageOps.exif_transpose(img)  # 폰이 적어 둔 '돌려 찍음'을 실제로 돌려 둔다
        except Exception as e:  # 회전 정보(EXIF)만 깨진 사진은 돌리지 않고 그대로 저장한다
            log.warning("photo exif_transpose skipped error=%s", type(e).__name__)
        rgb = img.convert("RGB")
        rgb.info.clear()  # 원본 주석(JPEG COM·PNG comment)이 새 JPEG 에 따라오지 않게 — 위치를 글로 적어 둔 경우가 있다
        out = io.BytesIO()
        rgb.save(out, "JPEG", quality=85)
    except ApiError:
        raise  # 위에서 일부러 낸 거절(예: 픽셀 제한)은 그 코드 그대로 — 아래에서 BAD_IMAGE 로 바뀌지 않게
    except (Image.DecompressionBombError, Image.DecompressionBombWarning) as e:  # 아주 큰 그림은 Pillow 가 먼저 막는다
        raise ApiError(400, "IMAGE_TOO_LARGE", "사진이 너무 커요") from e
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
        description="JPEG/PNG",
        json_schema_extra={"items": {"type": "string", "format": "binary"}},  # Swagger 에 [파일 선택] 버튼이 뜨게
    ),
):
    """받은 사진을 JPEG 로 다시 만들어 저장. 20장·10MB·30M 픽셀 제한. HEIC·같은 요청 한 번만은 이어서 채운다 (D17)."""
    require_member(room_id, user, db)
    if len(files) > UPLOAD_MAX_FILES:
        raise ApiError(400, "TOO_MANY_PHOTOS", f"사진은 한 번에 {UPLOAD_MAX_FILES}장까지 올릴 수 있어요")
    # 그림을 풀기 전에 장당 크기부터. 요청 전체는 여기 오기 전에 이미 다 받은 뒤 — 전체 상한은 Caddy(배포 서버)가 막는다
    for f in files:
        if f.size is None or f.size > UPLOAD_MAX_BYTES:
            raise ApiError(400, "PHOTO_TOO_BIG", f"사진 한 장은 {UPLOAD_MAX_BYTES // (1024 * 1024)}MB까지예요")
    # 전부 JPEG 로 바꾼 뒤에 저장소에 넣는다 — 중간에 깨진 사진이 있으면 앞 사진 파일만 남지 않게 (한 장씩 차례로, D17)
    # 한계: 저장소에 넣는 도중 고장·DB 저장 실패 때는 파일이 남을 수 있음. 막으려면 storage 에 지우기 기능 필요
    converted = [to_jpeg(f.file.read()) for f in files]
    batch_id = uuid.uuid4()
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
    return PhotoBatchOut(upload_batch_id=batch_id, photos=[photo_out(p) for p in photos])
