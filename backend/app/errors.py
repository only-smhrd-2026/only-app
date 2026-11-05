"""오류 형식 {detail, code} 통일. 500 에는 경로·예외 타입만 로그 (전사·토큰 유출 방지, D15)."""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

log = logging.getLogger("app")


class ApiError(StarletteHTTPException):
    def __init__(self, status_code: int, code: str, detail: str):
        super().__init__(status_code=status_code, detail=detail)
        self.code = code


def install_handlers(app: FastAPI) -> None:
    @app.exception_handler(StarletteHTTPException)
    def _http(request: Request, exc: StarletteHTTPException):
        code = getattr(exc, "code", f"HTTP_{exc.status_code}")
        return JSONResponse({"detail": exc.detail, "code": code}, status_code=exc.status_code, headers=exc.headers)

    @app.exception_handler(RequestValidationError)
    def _validation(request: Request, exc: RequestValidationError):
        # 입력값(input) 은 되돌려 주지 않는다. 위치와 메시지만.
        errors = [{"loc": e.get("loc"), "msg": e.get("msg")} for e in exc.errors()]
        return JSONResponse(
            {"detail": "입력값이 올바르지 않습니다", "code": "VALIDATION", "errors": errors},
            status_code=422,
        )

    # exception_handler(Exception) 은 쓰지 않는다: Starlette 가 응답 뒤 예외를 다시 던져 uvicorn 이 전체 트레이스백
    # (SQL 파라미터의 어르신 말, pydantic input_value 포함)을 로그에 남긴다. 미들웨어에서 삼켜 경로·타입만 남긴다 (D15).
    @app.middleware("http")
    async def _catch_all(request: Request, call_next):
        try:
            return await call_next(request)
        except Exception as exc:
            log.error("unhandled %s %s -> %s", request.method, request.url.path, type(exc).__name__)
            return JSONResponse({"detail": "서버 오류", "code": "INTERNAL"}, status_code=500)
