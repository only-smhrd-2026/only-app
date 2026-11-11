"""POST /api/stt — 녹음 → 글. 가족·어르신 공용. 오디오는 메모리에서만 쓰고 바로 버린다 (D6, NFR-AN-001)."""

import logging

from fastapi import APIRouter, File, Form, Request, UploadFile

from app.ai import stt
from app.config import STT_MAX_BYTES, STT_MAX_CHARS, STT_PER_DAY, settings
from app.deps import DB, CurrentActor
from app.errors import ApiError
from app.schemas.elder import SttOut
from app.security import daily_allowed, stt_allowed

log = logging.getLogger("app.stt")
router = APIRouter(tags=["stt"])


@router.post("/stt", response_model=SttOut)
def transcribe(
    request: Request,
    actor: CurrentActor,
    db: DB,
    audio: UploadFile = File(description="webm/opus 등, 5MB 이하"),
    hints: str | None = Form(default=None, description="이름·호칭 힌트, 쉼표 구분"),
):
    # 로그인·기기 확인(CurrentActor)을 통과한 요청만 센다. 돈이 드는 STT 를 무제한으로 부르지 못하게 (D46)
    if not stt_allowed(request.client.host if request.client else "unknown"):
        raise ApiError(429, "TOO_MANY_REQUESTS", "잠시 후 다시 말씀해 주세요")
    data = audio.file.read(STT_MAX_BYTES + 1)
    if len(data) > STT_MAX_BYTES:
        raise ApiError(413, "AUDIO_TOO_LARGE", "녹음 파일이 너무 커요 (5MB 초과)")
    if not data:
        raise ApiError(422, "AUDIO_EMPTY", "녹음이 비어 있어요")
    # 서버 전체 하루 상한은 유료 호출만 센다(mock 은 안 셈). 아래 try 안에서 던지면 503 으로 바뀌므로 그 앞에서 (D46)
    if settings.STT_PROVIDER != "mock" and not daily_allowed("stt", STT_PER_DAY):
        raise ApiError(429, "STT_DAILY_LIMIT", "오늘은 말로 답하기를 다 썼어요. 버튼을 눌러 답해 주세요.")
    db.close()  # 인증 확인에 쓴 DB 연결(CurrentActor 와 같은 세션)을 STT(최대 8초) 동안 쥐지 않게 돌려준다
    try:
        text, confidence = stt.transcribe(data, [h.strip() for h in hints.split(",")] if hints else [])
    except stt.BadAudio:
        raise ApiError(422, "AUDIO_INVALID", "녹음을 알아듣지 못했어요. 다시 말씀해 주세요.") from None
    except Exception as e:  # 미구현·키 없음·제공자 장애·시간 초과. 예외 글에는 주소가 섞일 수 있어 타입만 남긴다 (D15)
        log.warning("stt failed type=%s", type(e).__name__)
        raise ApiError(503, "STT_UNAVAILABLE", "음성 인식을 지금 쓸 수 없어요") from None
    if not text:
        # 말소리가 없었다. 빈 글을 돌려주면 화면의 [맞아요] 뒤 턴이 422 로 대화를 끝내 버린다
        raise ApiError(422, "STT_EMPTY", "잘 못 들었어요. 다시 말씀해 주세요.")
    return SttOut(transcript=text[:STT_MAX_CHARS], confidence=confidence)
