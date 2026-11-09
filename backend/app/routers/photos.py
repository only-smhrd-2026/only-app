"""사진 올리기 (BE-02, FR-ME-001/002/004, D17). 목록 보기·정정은 아직 stubs.py 에 있다."""

import io
import uuid

from fastapi import APIRouter, File, UploadFile
from PIL import Image, ImageOps

from app.deps import DB, CurrentUser, require_member
from app.errors import ApiError
from app.models import Photo
from app.schemas.photos import PhotoBatchOut, PhotoOut
from app.services import storage

router = APIRouter(prefix="/rooms/{room_id}/photos", tags=["photos"])


def to_jpeg(data: bytes) -> bytes:
    """그림만 꺼내 JPEG 로 새로 만든다. 원본의 EXIF(위치정보 포함)는 따라오지 않는다 (D17)."""
    try:
        img = ImageOps.exif_transpose(Image.open(io.BytesIO(data)))  # 폰이 적어 둔 '돌려 찍음'을 실제로 돌려 둔다
        out = io.BytesIO()
        img.convert("RGB").save(out, "JPEG", quality=85)
    except OSError as e:  # 사진이 아니거나 깨진 파일 (UnidentifiedImageError 도 OSError)
        raise ApiError(400, "BAD_IMAGE", "사진 파일을 열 수 없어요") from e
    return out.getvalue()


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
    """받은 사진을 JPEG 로 다시 만들어 저장. 20장·10MB·HEIC·같은 요청 한 번만은 이어서 채운다 (D17)."""
    require_member(room_id, user, db)
    batch_id = uuid.uuid4()
    photos = []
    for i, f in enumerate(files):  # 한 장씩 차례로 (D17 순차 처리)
        key = f"rooms/{room_id}/{batch_id}/{i}.jpg"
        storage.put(key, to_jpeg(f.file.read()))
        photo = Photo(
            room_id=room_id, uploaded_by=user.user_id, upload_batch_id=batch_id, object_key=key, source="FAMILY"
        )
        db.add(photo)
        photos.append(photo)
    db.commit()
    return PhotoBatchOut(upload_batch_id=batch_id, photos=[photo_out(p) for p in photos])
