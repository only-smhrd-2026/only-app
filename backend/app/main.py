"""하루한장 API. 실행: backend 폴더에서 `uv run uvicorn app.main:app --reload` → http://localhost:8000/docs"""

import logging
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI

from app.config import now_kst, settings
from app.errors import install_handlers
from app.routers import (
    auth,
    devices,
    diaries,
    elder,
    invites,
    media,
    mood,
    notifications,
    photos,
    rooms,
    sessions,
    stt,
    stubs,
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

api = APIRouter(prefix="/api")
for r in (
    auth.router,
    rooms.router,
    invites.router,
    devices.router,
    elder.router,
    stt.router,
    sessions.router,
    diaries.router,
    media.router,
    photos.router,
    notifications.router,
    mood.router,
    *stubs.routers,
):
    api.include_router(r)


@api.get("/health", tags=["health"])
def health():
    return {"ok": True, "env": settings.APP_ENV, "time": now_kst().isoformat()}


app.include_router(api)
