from pydantic import BaseModel


class ErrorOut(BaseModel):
    """모든 오류 응답 모양 (app/errors.py)."""

    detail: str
    code: str


class OkOut(BaseModel):
    ok: bool = True


class NotImplementedOut(BaseModel):
    """빈 API 표시용. 담당자가 채우면 이 모델을 지운다."""

    detail: str = "아직 구현 전입니다"
    code: str = "NOT_IMPLEMENTED"
