"""POST /api/stt — 녹음 → 글. 가족·어르신 공용. 오디오는 메모리에서만 쓰고 바로 버린다 (D6, NFR-AN-001)."""

from fastapi import APIRouter, File, Form, UploadFile

from app.ai import stt
from app.config import STT_MAX_BYTES
from app.deps import CurrentActor
from app.errors import ApiError
from app.schemas.elder import SttOut

router = APIRouter(tags=["stt"])


@router.post("/stt", response_model=SttOut)
def transcribe(
    actor: CurrentActor,
    audio: UploadFile = File(description="webm/opus 등, 5MB 이하"),
    hints: str | None = Form(default=None, description="이름·호칭 힌트, 쉼표 구분"),
):
    data = audio.file.read(STT_MAX_BYTES + 1)
    if len(data) > STT_MAX_BYTES:
        raise ApiError(413, "AUDIO_TOO_LARGE", "녹음 파일이 너무 커요 (5MB 초과)")
    if not data:
        raise ApiError(422, "AUDIO_EMPTY", "녹음이 비어 있어요")
    try:
        text, confidence = stt.transcribe(data, [h.strip() for h in hints.split(",")] if hints else [])
    except NotImplementedError:
        raise ApiError(503, "STT_UNAVAILABLE", "음성 인식을 지금 쓸 수 없어요") from None
    return SttOut(transcript=text, confidence=confidence)
