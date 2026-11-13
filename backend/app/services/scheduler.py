"""예약 작업 틀 (D9). APScheduler in-process, 시간대 Asia/Seoul 고정. 세 함수의 본문은 담당자가 채운다.

- 매시 정각 가족방별 memory_time 기준 오늘의 한 장 선정 — 홈에서도 보정한다 (D9).
- 19:00 일기 알림 (천주웅)
- 19:00 이틀째 기록 없음 가족 알림 (천주웅) — 기록 = 어르신이 말한 대화(models.ELDER_SPOKE)·어르신 일기
- 일요일 19:00 주간 요약 (배선 천주웅, 요약 AI 홍진성)
compose 는 restart: unless-stopped, uvicorn --workers 1 전제 (잡이 두 번 돌지 않게).
"""

from __future__ import annotations

import logging
from datetime import timedelta

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import select

from app.config import NO_RECORD_DAYS, TZ, WEEKLY_HOUR, now_kst, today_kst
from app.db import SessionLocal
from app.models import ELDER_SPOKE, DailyPick, Diary, FamilyRoom, Notification, TalkSession
from app.routers.devices import notify_family
from app.services import picks, weekly

log = logging.getLogger("app.jobs")
scheduler = BackgroundScheduler(timezone=TZ)


def select_daily_picks() -> None:
    """설정 시간이 지났고 오늘의 한 장이 없는 가족방(ACTIVE)을 채운다. 방 하나가 실패해도 나머지 방은 계속."""
    now = now_kst()
    today = today_kst()
    picked = failed = 0
    with SessionLocal() as db:
        already_picked = select(DailyPick.room_id).where(DailyPick.pick_date == today)
        room_ids = db.scalars(
            select(FamilyRoom.room_id)
            .where(
                FamilyRoom.status == "ACTIVE",
                FamilyRoom.memory_time <= now.time(),
                FamilyRoom.room_id.not_in(already_picked),
            )
            .order_by(FamilyRoom.room_id)  # 처리 순서를 고정 (로그·테스트가 매번 같게)
        ).all()
        for room_id in room_ids:
            try:
                picked += picks.select_pick(db, room_id, today) is not None
            except Exception as e:  # 실패한 방은 다음 정각·홈 보정이 다시 시도한다
                db.rollback()  # 안 하면 PG 가 'current transaction is aborted' 로 다음 방까지 거부
                failed += 1
                log.warning("job select_daily_picks room=%s error=%s", room_id, type(e).__name__)
    log.info("job select_daily_picks rooms=%d picked=%d failed=%d", len(room_ids), picked, failed)


def diary_reminders() -> None:
    """일기 시간이 지난 연결된 가족방에 오늘 어르신 일기가 없으면 알림을 하루 한 번 만든다."""
    now = now_kst()
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    with SessionLocal() as db:
        wrote_today = select(Diary.room_id).where(
            Diary.author_type == "ELDER", Diary.status == "POSTED", Diary.posted_at >= day_start
        )
        reminded_today = select(Notification.room_id).where(
            Notification.kind == "DIARY_REMINDER", Notification.sent_at >= day_start
        )
        rooms = db.scalars(
            select(FamilyRoom)
            .where(
                FamilyRoom.status == "ACTIVE",
                FamilyRoom.device_token_hash.is_not(None),
                FamilyRoom.diary_time <= now.time(),
                FamilyRoom.room_id.not_in(wrote_today),
                FamilyRoom.room_id.not_in(reminded_today),
            )
            .order_by(FamilyRoom.room_id)
        ).all()
        for room in rooms:
            db.add(
                Notification(
                    room_id=room.room_id,
                    target_type="ELDER",
                    kind="DIARY_REMINDER",
                    title=f"{room.elder_name} {room.elder_honorific}, 오늘 일기를 써 볼까요?",
                    link_screen="ELDER_DIARY_001",
                    sent_at=now,
                )
            )
        db.commit()
    log.info("job diary_reminders rooms=%d", len(rooms))


def no_record_alerts() -> None:
    """연결 후 이틀째 어르신이 말한 대화·어르신 일기가 없는 방의 가족에게 하루 한 번 알린다."""
    now = now_kst()
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    since = day_start - timedelta(days=NO_RECORD_DAYS - 1)
    with SessionLocal() as db:
        talked = select(TalkSession.room_id).where(TalkSession.started_at >= since, ELDER_SPOKE)
        wrote = select(Diary.room_id).where(
            Diary.author_type == "ELDER", Diary.status == "POSTED", Diary.posted_at >= since
        )
        alerted_today = select(Notification.room_id).where(
            Notification.kind == "NO_RECORD_2D", Notification.sent_at >= day_start
        )
        rooms = db.scalars(
            select(FamilyRoom)
            .where(
                FamilyRoom.status == "ACTIVE",
                FamilyRoom.device_token_hash.is_not(None),
                FamilyRoom.device_connected_at < since,
                FamilyRoom.room_id.not_in(talked),
                FamilyRoom.room_id.not_in(wrote),
                FamilyRoom.room_id.not_in(alerted_today),
            )
            .order_by(FamilyRoom.room_id)
        ).all()
        for room in rooms:
            notify_family(
                db,
                room.room_id,
                "NO_RECORD_2D",
                f"{room.elder_name} 님이 이틀째 기록이 없어요",
                body="전화 한 통 드려 보세요",
                link="HOME_001",
            )
        db.commit()
    log.info("job no_record_alerts rooms=%d", len(rooms))


def weekly_summaries() -> None:
    """활성 가족방의 최근 완료된 주간 집계를 만든다. 한 방이 실패해도 다음 방을 계속한다."""
    now = now_kst()
    failed = 0
    with SessionLocal() as db:
        room_ids = db.scalars(
            select(FamilyRoom.room_id).where(FamilyRoom.status == "ACTIVE").order_by(FamilyRoom.room_id)
        ).all()
        for room_id in room_ids:
            try:
                weekly.build(db, room_id, now)
            except Exception as e:
                db.rollback()
                failed += 1
                log.warning("job weekly_summaries room=%s error=%s", room_id, type(e).__name__)
    log.info("job weekly_summaries rooms=%d failed=%d", len(room_ids), failed)


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
        no_record_alerts, CronTrigger(hour=19, minute=0, timezone=TZ), id="no_record_alerts", replace_existing=True
    )
    scheduler.add_job(
        weekly_summaries,
        CronTrigger(day_of_week="sun", hour=WEEKLY_HOUR, minute=0, timezone=TZ),
        id="weekly_summaries",
        replace_existing=True,
    )
    scheduler.start()
    catch_up()


def stop() -> None:
    if scheduler.running:
        scheduler.shutdown(wait=False)
