"""하루한장 API. 실행: backend 폴더에서 `uv run uvicorn app.main:app --reload` → http://localhost:8000/docs"""

import logging
from contextlib import asynccontextmanager
from time import perf_counter

from fastapi import APIRouter, FastAPI, Request
from sqlalchemy import text
from starlette.responses import JSONResponse

from app.ai import llm
from app.config import now_kst, settings
from app.deps import DB
from app.errors import install_handlers
from app.routers import (
    account,
    alerts,
    auth,
    calendar,
    care,
    devices,
    diaries,
    elder,
    family_diary,
    integration,
    invites,
    kakao,
    media,
    mood,
    notifications,
    photos,
    push,
    rooms,
    sessions,
    stt,
    weekly,
)
from app.services import scheduler

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI):
    if settings.SCHEDULER_ENABLED:
        scheduler.start()
    yield
    scheduler.stop()


app = FastAPI(title="하루한장 API", version="0.1.0", lifespan=lifespan)
install_handlers(app)


@app.middleware("http")
async def log_request_timing(request: Request, call_next):
    if request.url.path == "/api/health":
        return await call_next(request)
    started = perf_counter()
    response = await call_next(request)
    route = getattr(request.scope.get("route"), "path", "-")
    # FastAPI can expose the original router path before applying the API prefix.
    prefix = f"{api.prefix}/"
    if route != "-" and request.url.path.startswith(prefix) and not route.startswith(prefix):
        route = api.prefix + route
    logging.getLogger("app.req").info(
        "req method=%s route=%s status=%s ms=%d",
        request.method,
        route,
        response.status_code,
        (perf_counter() - started) * 1000,
    )
    return response


api = APIRouter(prefix="/api")
for r in (
    auth.router,
    account.router,
    kakao.router,
    rooms.router,
    invites.router,
    devices.router,
    elder.router,
    stt.router,
    sessions.router,
    diaries.router,
    calendar.router,
    family_diary.router,
    media.router,
    photos.router,
    notifications.router,
    mood.router,
    alerts.router,
    care.router,
    weekly.router,
    integration.router,
    push.router,
):
    api.include_router(r)


@api.get("/health", tags=["health"])
def health(db: DB):
    try:
        db.execute(text("SELECT 1"))
    except Exception as e:
        logging.getLogger("app.health").warning("health db error=%s", type(e).__name__)  # 예외 종류만 (D15)
        return JSONResponse(status_code=503, content={"ok": False, "db": False})
    # llm_fail_streak: AI 호출이 연달아 실패한 수 — 0 이 아니면 고정 문장으로 돌고 있다 (11/26, 배포 확인 때 같이 본다)
    return {
        "ok": True,
        "env": settings.APP_ENV,
        "time": now_kst().isoformat(),
        "db": True,
        "llm_fail_streak": llm.fail_streak(),
    }


app.include_router(api)
