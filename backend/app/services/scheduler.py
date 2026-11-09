"""예약 작업 틀 (D9). APScheduler in-process, 시간대 Asia/Seoul 고정. 세 함수의 본문은 담당자가 채운다.

- 09:00 오늘의 한 장 선정 (천주웅) — 놓치면 GET /api/elder/home 이 보정한다 (D9).
- 19:00 일기 알림 (천주웅)
- 일요일 19:00 주간 요약 (배선 천주웅, 요약 AI 홍진성)
compose 는 restart: unless-stopped, uvicorn --workers 1 전제 (잡이 두 번 돌지 않게).
"""

from __future__ import annotations

import logging

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from app.config import TZ

log = logging.getLogger("app.jobs")
scheduler = BackgroundScheduler(timezone=TZ)


def select_daily_picks() -> None:
    """09:00 — 가족방마다 오늘의 한 장 선정.

    TODO(천주웅): 가족방별 memory_time 이 다르므로 매 시 정각에 돌면서 memory_time <= now 이고
    오늘 pick 이 없는 방만 services.picks.select_pick() 으로 채우는 쪽을 권장.
    """
    log.info("job select_daily_picks: 아직 비어 있음")


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
        select_daily_picks, CronTrigger(hour=9, minute=0, timezone=TZ), id="select_daily_picks", replace_existing=True
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
