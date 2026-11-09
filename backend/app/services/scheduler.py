"""예약 작업 틀 (D9). APScheduler in-process, 시간대 Asia/Seoul 고정. 세 함수의 본문은 담당자가 채운다.

- 매시 정각 가족방별 memory_time 기준 오늘의 한 장 선정 — 홈에서도 보정한다 (D9).
- 19:00 일기 알림 (천주웅)
- 일요일 19:00 주간 요약 (배선 천주웅, 요약 AI 홍진성)
compose 는 restart: unless-stopped, uvicorn --workers 1 전제 (잡이 두 번 돌지 않게).
"""

from __future__ import annotations

import logging

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import select

from app.config import TZ, now_kst, today_kst
from app.db import SessionLocal
from app.models import DailyPick, FamilyRoom
from app.services import picks

log = logging.getLogger("app.jobs")
scheduler = BackgroundScheduler(timezone=TZ)


def select_daily_picks() -> None:
    """설정 시간이 지났고 오늘의 한 장이 없는 가족방을 채운다."""
    now = now_kst()
    today = today_kst()
    with SessionLocal() as db:
        already_picked = select(DailyPick.room_id).where(DailyPick.pick_date == today)
        room_ids = db.scalars(
            select(FamilyRoom.room_id).where(
                FamilyRoom.memory_time <= now.time(),
                FamilyRoom.room_id.not_in(already_picked),
            )
        ).all()
        for room_id in room_ids:
            picks.select_pick(db, room_id, today)


def diary_reminders() -> None:
    """19:00 — 오늘 일기가 없는 어르신에게 DIARY_REMINDER 알림 1회. TODO(천주웅)."""
    log.info("job diary_reminders: 아직 비어 있음")


def weekly_summaries() -> None:
    """일요일 19:00 — 집계 창 [지난 일요일 19:00, 이번 일요일 19:00) 로 주간 요약 생성 + WEEKLY_READY 알림 (D19).

    TODO(천주웅 배선 / 홍진성 요약 AI).
    """
    log.info("job weekly_summaries: 아직 비어 있음")


def catch_up() -> None:
    """기동 시 놓친 작업 보정 (D9). 예: 지난 일요일 주간 요약이 없으면 지금 생성. TODO(천주웅)."""
    log.info("catch_up: 아직 비어 있음")


def start() -> None:
    scheduler.add_job(
        select_daily_picks, CronTrigger(minute=0, timezone=TZ), id="select_daily_picks", replace_existing=True
    )
    scheduler.add_job(
        diary_reminders, CronTrigger(hour=19, minute=0, timezone=TZ), id="diary_reminders", replace_existing=True
    )
    scheduler.add_job(
        weekly_summaries,
        CronTrigger(day_of_week="sun", hour=19, minute=0, timezone=TZ),
        id="weekly_summaries",
        replace_existing=True,
    )
    scheduler.start()
    catch_up()


def stop() -> None:
    if scheduler.running:
        scheduler.shutdown(wait=False)
