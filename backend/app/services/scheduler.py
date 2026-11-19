"""예약 작업 틀 (D9). APScheduler in-process, 시간대 Asia/Seoul 고정. 세 함수의 본문은 담당자가 채운다.

- 매시 정각 가족방별 memory_time 기준 오늘의 한 장 선정 — 홈에서도 보정한다 (D9).
- 매시 1분 추억 알림 — 오늘의 한 장을 아직 안 본 어르신 기기에 푸시 (FR-NT-002, services/push.py). 일기 알림도 푸시로
- 19:00 일기 알림 (천주웅)
- 19:00 이틀째 기록 없음 가족 알림 (천주웅) — 기록 = 어르신이 말한 대화(models.ELDER_SPOKE)·어르신 일기
- 일요일 19:00 주간 요약 (배선 천주웅, 요약 AI 홍진성)
- 10분마다 분류 전 가족 사진 분류 (AI-04, 홍진성 — D71)
- 04:00 어제 대화에서 이야기 기억 뽑기·보관 기간 지난 기억 지우기 (AI-07, 홍진성 — D77)
- 5분마다 확인 안 된 위급 알림을 가족에게 한 번 더 (홍진성 — 11/19 응급)
compose 는 restart: unless-stopped, uvicorn --workers 1 전제 (잡이 두 번 돌지 않게).
"""

from __future__ import annotations

import logging
from datetime import timedelta

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import select

from app.ai import classify, story
from app.ai.weekly import summarize
from app.config import (
    CLASSIFY_EVERY_MIN,
    DAILY_ALERT_HOUR,
    MEMORY_REMINDER_HOURS,
    NO_RECORD_DAYS,
    STORY_HOUR,
    TZ,
    URGENT_CHECK_EVERY_MIN,
    WEEKLY_HOUR,
    now_kst,
    today_kst,
)
from app.db import SessionLocal
from app.models import ELDER_SPOKE, DailyPick, Diary, FamilyRoom, Notification, TalkSession, WeeklySummary
from app.routers.devices import notify_family
from app.services import alerts, picks, push, weekly

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
            # 푸시는 일기 시간 뒤 MEMORY_REMINDER_HOURS 안에만 — 밤에 서버를 다시 띄울 때(기동 보정 catch_up)
            # 어르신 폰이 뒤늦게 울리지 않게. 앱 안 알림 줄은 그대로 만든다
            if now.hour < DAILY_ALERT_HOUR + MEMORY_REMINDER_HOURS:
                push.queue_elder(db, room.room_id, "DIARY_REMINDER")
        db.commit()
    log.info("job diary_reminders rooms=%d", len(rooms))


def memory_reminders() -> None:
    """추억 시간이 지난 연결된 가족방에 오늘의 한 장이 아직 그대로면(PENDING) 알림을 하루 한 번 만들고 푸시한다.

    이야기를 마쳤거나(COMPLETED) 건너뛴(SKIPPED) 날은 보내지 않는다. 일기 알림과 합쳐 어르신 푸시는 하루 최대 2건.
    추억 시간 뒤 MEMORY_REMINDER_HOURS 안에만 보낸다 — 그때를 놓친 날(서버가 꺼져 있었음)은 밤에 뒤늦게 울리지 않는다.
    (FR-NT-002)
    """
    now = now_kst()
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    since = max(day_start, now - timedelta(hours=MEMORY_REMINDER_HOURS)).time()
    with SessionLocal() as db:
        waiting = select(DailyPick.room_id).where(DailyPick.pick_date == now.date(), DailyPick.status == "PENDING")
        reminded_today = select(Notification.room_id).where(
            Notification.kind == "MEMORY_REMINDER", Notification.sent_at >= day_start
        )
        rooms = db.scalars(
            select(FamilyRoom)
            .where(
                FamilyRoom.status == "ACTIVE",
                FamilyRoom.device_token_hash.is_not(None),
                FamilyRoom.memory_time <= now.time(),
                FamilyRoom.memory_time >= since,
                FamilyRoom.room_id.in_(waiting),
                FamilyRoom.room_id.not_in(reminded_today),
            )
            .order_by(FamilyRoom.room_id)
        ).all()
        for room in rooms:
            db.add(
                Notification(
                    room_id=room.room_id,
                    target_type="ELDER",
                    kind="MEMORY_REMINDER",
                    title=f"{room.elder_name} {room.elder_honorific}, 오늘의 한 장이 기다리고 있어요",
                    link_screen="ELDER_TODAY_001",
                    sent_at=now,
                )
            )
            push.queue_elder(db, room.room_id, "MEMORY_REMINDER")
        db.commit()
    log.info("job memory_reminders rooms=%d", len(rooms))


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
        # 조용한 날이 이어지면 알림 목록에는 날마다 남기되 폰은 첫날만 울린다 — 날마다 울리면 가족이 알림을 꺼 버리고,
        # 그러면 위급 알림도 못 받는다 (11/19).
        # ponytail: 첫날 알림을 놓치면 폰은 다시 안 울린다(알림 목록·가족 홈에는 남는다). 며칠마다 다시 울리려면 여기서
        repeated = set(
            db.scalars(
                select(Notification.room_id).where(
                    Notification.kind == "NO_RECORD_2D",
                    Notification.sent_at >= day_start - timedelta(days=1),
                    Notification.sent_at < day_start,
                )
            )
        )
        for room in rooms:
            notify_family(
                db,
                room.room_id,
                "NO_RECORD_2D",
                f"{room.elder_name} 님이 이틀째 기록이 없어요",
                body="전화 한 통 드려 보세요",
                link="HOME_001",
                to_phone=room.room_id not in repeated,
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
                ready = weekly.build(db, room_id, now)
                start, end, week_start = weekly.window(now)
                row = db.scalar(
                    select(WeeklySummary).where(
                        WeeklySummary.room_id == room_id,
                        WeeklySummary.week_start == week_start,
                    )
                )
                # 알림 저장이 실패한 주도 다음 기동에 보정한다. 빈 주는 계속 알리지 않는다.
                if not ready and row is not None and row.published_at is None:
                    ready = bool(
                        db.scalar(
                            select(TalkSession.session_id)
                            .where(
                                TalkSession.room_id == room_id,
                                TalkSession.started_at >= start,
                                TalkSession.started_at < end,
                                ELDER_SPOKE,
                            )
                            .limit(1)
                        )
                    ) or bool(
                        db.scalar(
                            select(Diary.diary_id)
                            .where(
                                Diary.room_id == room_id,
                                Diary.author_type == "ELDER",
                                Diary.status == "POSTED",
                                Diary.posted_at >= start,
                                Diary.posted_at < end,
                            )
                            .limit(1)
                        )
                    )
                if ready:
                    try:
                        summarize(db, room_id, week_start)
                    except Exception as exc:
                        db.rollback()
                        log.warning("job weekly_summary_ai room=%s error=%s", room_id, type(exc).__name__)
                    row = db.scalar(
                        select(WeeklySummary)
                        .where(
                            WeeklySummary.room_id == room_id,
                            WeeklySummary.week_start == week_start,
                        )
                        .with_for_update()
                    )
                    if row is not None and row.published_at is None:
                        room = db.get(FamilyRoom, room_id)
                        notify_family(
                            db,
                            room_id,
                            "WEEKLY_READY",
                            f"{room.elder_name} 님의 이번 주 이야기가 도착했어요",
                            link="WEEKLY_001",
                        )
                        row.published_at = now_kst()
                        db.commit()
            except Exception as e:
                db.rollback()
                failed += 1
                log.warning("job weekly_summaries room=%s error=%s", room_id, type(e).__name__)
    log.info("job weekly_summaries rooms=%d failed=%d", len(room_ids), failed)


def classify_photos() -> None:
    """분류 전 가족 사진을 분류한다 (AI-04, D71). 한 번에 CLASSIFY_BATCH 장 — 남은 것은 다음 차례에."""
    with SessionLocal() as db:
        done, left = classify.run_pending(db)
    if done or left:  # 할 일이 없을 때는 10분마다 줄을 남기지 않는다
        log.info("job classify_photos done=%d left=%d", done, left)


def story_facts() -> None:
    """어제 대화에서 이야기 기억을 뽑고, 보관 기간이 지난 기억을 지운다 (AI-07, D77)."""
    with SessionLocal() as db:
        rooms, kept = story.run(db, today_kst() - timedelta(days=1))
    log.info("job story_facts rooms=%d kept=%d", rooms, kept)


def urgent_reminders() -> None:
    """위급 알림에 아무도 [제가 연락했어요]를 누르지 않았으면 가족에게 한 번 더 알린다 (11/19 응급)."""
    with SessionLocal() as db:
        told = alerts.remind(db)
    if told:  # 할 일이 없을 때는 5분마다 줄을 남기지 않는다
        log.info("job urgent_reminders rooms=%d", told)


def catch_up() -> None:
    """기동 시 놓친 작업 보정 (D9). 예: 지난 일요일 주간 요약이 없으면 지금 생성. TODO(천주웅)."""
    jobs = [weekly_summaries]
    if now_kst().hour >= DAILY_ALERT_HOUR:
        jobs.extend([diary_reminders, no_record_alerts])
    for job in jobs:
        try:
            job()
        except Exception as exc:
            log.warning("catch_up job=%s error=%s", job.__name__, type(exc).__name__)
    log.info("catch_up jobs=%d", len(jobs))


def start() -> None:
    scheduler.add_job(
        select_daily_picks, CronTrigger(minute=0, timezone=TZ), id="select_daily_picks", replace_existing=True
    )
    # 매시 1분: 정각에 고른 오늘의 한 장이 있어야 알림이 가므로 사진 고르기(정각) 바로 뒤에 돈다
    scheduler.add_job(
        memory_reminders, CronTrigger(minute=1, timezone=TZ), id="memory_reminders", replace_existing=True
    )
    scheduler.add_job(
        diary_reminders,
        CronTrigger(hour=DAILY_ALERT_HOUR, minute=0, timezone=TZ),
        id="diary_reminders",
        replace_existing=True,
    )
    scheduler.add_job(
        no_record_alerts,
        CronTrigger(hour=DAILY_ALERT_HOUR, minute=0, timezone=TZ),
        id="no_record_alerts",
        replace_existing=True,
    )
    scheduler.add_job(
        weekly_summaries,
        CronTrigger(day_of_week="sun", hour=WEEKLY_HOUR, minute=0, timezone=TZ),
        id="weekly_summaries",
        replace_existing=True,
    )
    scheduler.add_job(
        classify_photos,
        CronTrigger(minute=f"*/{CLASSIFY_EVERY_MIN}", timezone=TZ),
        id="classify_photos",
        replace_existing=True,
    )
    scheduler.add_job(
        story_facts, CronTrigger(hour=STORY_HOUR, minute=0, timezone=TZ), id="story_facts", replace_existing=True
    )
    scheduler.add_job(
        urgent_reminders,
        CronTrigger(minute=f"*/{URGENT_CHECK_EVERY_MIN}", timezone=TZ),
        id="urgent_reminders",
        replace_existing=True,
    )
    scheduler.start()
    catch_up()


def stop() -> None:
    if scheduler.running:
        scheduler.shutdown(wait=False)
