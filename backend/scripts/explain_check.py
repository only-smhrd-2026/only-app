"""별도 시험 DB에 1년 치 가상 자료를 넣어 화면 조회와 인덱스 후보를 비교한다.

backend에서 uv run python -m scripts.explain_check [--keep].
후보 인덱스는 시험 DB의 savepoint 안에서만 만들고 측정 후 되돌린다.
표의 시간은 첫 실행을 제외한 EXPLAIN 실행 3회의 중앙값이며 실제 글 내용은 출력하지 않는다.
"""

from __future__ import annotations

import argparse
import os
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from pathlib import Path
from statistics import median

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection, Engine, make_url

TEST_DB = "only_app_explain"
ROOT = Path(__file__).resolve().parents[2]
ROOM_ID = 501


@dataclass(frozen=True)
class Query:
    name: str
    sql: str


@dataclass(frozen=True)
class Candidate:
    name: str
    table: str
    ddl: str
    queries: tuple[str, ...]


CANDIDATES = (
    Candidate(
        "ix_explain_diaries_posted",
        "diaries",
        "CREATE INDEX ix_explain_diaries_posted ON diaries (room_id, posted_at DESC, diary_id DESC) "
        "WHERE status = 'POSTED'",
        ("일기 첫 쪽", "일기 다음 쪽"),
    ),
    Candidate(
        "ix_explain_notifications_latest",
        "notifications",
        "CREATE INDEX ix_explain_notifications_latest ON notifications "
        "(target_user_id, sent_at DESC, notification_id DESC) WHERE target_type = 'FAMILY'",
        ("알림 목록",),
    ),
    Candidate(
        "ix_explain_family_news",
        "diaries",
        "CREATE INDEX ix_explain_family_news ON diaries (room_id, posted_at DESC, diary_id DESC) "
        "WHERE status = 'POSTED' AND author_type = 'FAMILY' AND elder_read_at IS NULL",
        ("안 들은 가족 소식",),
    ),
    Candidate(
        "ix_explain_story_used",
        "story_facts",
        "CREATE INDEX ix_explain_story_used ON story_facts (room_id, used_at) WHERE used_at IS NOT NULL",
        ("오늘 물은 이야기 기억",),
    ),
    Candidate(
        "ix_explain_photos_latest",
        "photos",
        "CREATE INDEX ix_explain_photos_latest ON photos (room_id, uploaded_at DESC, photo_id DESC) "
        "WHERE status = 'ACTIVE' AND source IN ('FAMILY', 'ELDER_CAMERA')",
        ("사진 목록",),
    ),
    Candidate(
        "ix_explain_pick_candidates",
        "photos",
        "CREATE INDEX ix_explain_pick_candidates ON photos (room_id, uploaded_at, photo_id) "
        "WHERE status = 'ACTIVE' AND source = 'FAMILY' AND usable IS NOT FALSE",
        ("오늘 사진 후보",),
    ),
)


def admin_engine(database_url: str) -> Engine:
    url = make_url(database_url)
    if url.get_backend_name() != "postgresql":
        raise ValueError("PostgreSQL 연결에서만 실행할 수 있어요")
    if url.database == TEST_DB:
        raise ValueError("현재 연결 DB가 시험 DB와 같아 실행하지 않았어요")
    return create_engine(url.set(database="postgres"), isolation_level="AUTOCOMMIT", hide_parameters=True)


def populate(conn: Connection, now: datetime) -> None:
    """서버 generate_series로만 만든 가상 자료. 운영·테스트 DB에서 복사하지 않는다."""
    conn.exec_driver_sql((ROOT / "db/schema.sql").read_text("utf-8"))
    conn.execute(text("INSERT INTO users (login_type, name) SELECT 'TEST', '가상 가족' FROM generate_series(1,1000)"))
    conn.execute(
        text("""
        INSERT INTO family_rooms (elder_name, elder_honorific, owner_user_id)
        SELECT '가상 어르신', '어르신', g FROM generate_series(1,1000) g
    """)
    )
    conn.execute(
        text("""
        INSERT INTO room_members (room_id, user_id, relation_tag)
        SELECT g, g, 'CHILD' FROM generate_series(1,1000) g
    """)
    )
    conn.execute(
        text("""
        INSERT INTO photos (room_id, uploaded_by, upload_batch_id, object_key, source, status,
                            uploaded_at, usable, is_old, season, activity, category, confidence, analyzed_at)
        SELECT (g-1)%1000+1, (g-1)%1000+1, md5('photo-'||g)::uuid,
               'rooms/'||((g-1)%1000+1)||'/'||md5('photo-'||g)||'/0.jpg',
               CASE WHEN ((g-1)/1000)%7=0 THEN 'ELDER_CAMERA'
                    WHEN ((g-1)/1000)%11=0 THEN 'FAMILY_DIARY' ELSE 'FAMILY' END,
               CASE WHEN ((g-1)/1000)%10=0 THEN 'DELETED' ELSE 'ACTIVE' END,
               CAST(:now AS timestamptz) - ((g-1)/1000)*365.0/99 * interval '1 day',
               CASE WHEN ((g-1)/1000)%13=0 THEN false WHEN ((g-1)/1000)%5=0 THEN NULL ELSE true END,
               true, 'SPRING', '모내기', '농기구', 0.90, CAST(:now AS timestamptz)
        FROM generate_series(1,100000) g
    """),
        {"now": now},
    )
    conn.execute(
        text("""
        INSERT INTO daily_picks (room_id, pick_date, photo_id, status)
        SELECT (g-1)%1000+1, CAST(:now AS date) - floor(((g-1)/1000)*365.0/299)::integer,
               (((g-1)/1000)%100)*1000+(g-1)%1000+1,
               CASE WHEN ((g-1)/1000)%8=0 THEN 'SKIPPED' ELSE 'COMPLETED' END
        FROM generate_series(1,300000) g
    """),
        {"now": now},
    )
    conn.execute(
        text("""
        INSERT INTO sessions (session_id, room_id, kind, photo_id, input_mode, started_at, ended_at,
                              end_reason, turn_count, duration_sec, private_flag, turns)
        SELECT md5('session-'||g)::uuid, (g-1)%1000+1,
               CASE WHEN ((g-1)/1000)%3=0 THEN 'DIARY' WHEN ((g-1)/1000)%3=1 THEN 'ALBUM' ELSE 'MEMORY' END,
               (((g-1)/1000)%100)*1000+(g-1)%1000+1, 'VOICE',
               CAST(:now AS timestamptz) - ((g-1)/1000)*365.0/299 * interval '1 day',
               CAST(:now AS timestamptz) - ((g-1)/1000)*365.0/299 * interval '1 day' + interval '2 minutes',
               'COMPLETED', 6, 120, ((g-1)/1000)%20=0,
               CASE WHEN ((g-1)/1000)%8=0 THEN '[]'::jsonb ELSE
                   '[{"turn_no": 1,"speaker":"AI","text":"어떤 기억이 떠오르세요?"},
                     {"turn_no": 2,"speaker":"ELDER","text":"마당에서 꽃을 가꾸던 일이 떠올라요"},
                     {"turn_no": 3,"speaker":"AI","text":"누구와 함께하셨어요?"},
                     {"turn_no": 4,"speaker":"ELDER","text":"가족과 함께 마당에서 꽃을 가꾸었어요"},
                     {"turn_no": 5,"speaker":"AI","text":"어떤 꽃을 가꾸셨어요?"},
                     {"turn_no": 6,"speaker":"ELDER","text":"여러 가지 꽃을 가꾸었어요"}]'::jsonb END
        FROM generate_series(1,300000) g
    """),
        {"now": now},
    )
    conn.execute(
        text("""
        INSERT INTO diaries (room_id, author_type, author_user_id, body, mood, illustration_type,
                             request_id, posted_at, status, elder_read_at)
        SELECT (g-1)%1000+1, CASE WHEN ((g-1)/1000)%3=0 THEN 'FAMILY' ELSE 'ELDER' END,
               CASE WHEN ((g-1)/1000)%3=0 THEN (g-1)%1000+1 ELSE NULL END,
               '가상 일기입니다. 마당에서 꽃을 가꾸었어요.', 'GOOD', 'NONE', md5('diary-'||g)::uuid,
               CAST(:now AS timestamptz) - ((g-1)/1000)*365.0/299 * interval '1 day',
               CASE WHEN ((g-1)/1000)%10=0 THEN 'DELETED' ELSE 'POSTED' END,
               CASE WHEN ((g-1)/1000)%4=0 THEN CAST(:now AS timestamptz) ELSE NULL END
        FROM generate_series(1,300000) g
    """),
        {"now": now},
    )
    conn.execute(
        text("""
        INSERT INTO notifications (room_id, target_type, target_user_id, kind, title, sent_at, read_at)
        SELECT (g-1)%1000+1, CASE WHEN ((g-1)/1000)%10=0 THEN 'ELDER' ELSE 'FAMILY' END,
               CASE WHEN ((g-1)/1000)%10=0 THEN NULL ELSE (g-1)%1000+1 END,
               'DIARY_POSTED', '가상 일기 소식',
               CAST(:now AS timestamptz) - ((g-1)/1000)*365.0/999 * interval '1 day',
               CASE WHEN ((g-1)/1000)%4=0 THEN NULL ELSE CAST(:now AS timestamptz) END
        FROM generate_series(1,1000000) g
    """),
        {"now": now},
    )
    conn.execute(
        text("""
        INSERT INTO story_facts (room_id, session_id, source_turn_no, fact_text, kind, fact_date,
                                 is_active, used_at, expires_at)
        SELECT (g-1)%1000+1, md5('session-'||g)::uuid, 2, '마당에서 꽃을 가꾸셨다고 해요',
               CASE WHEN ((g-1)/1000)%2=0 THEN 'PLAN' ELSE 'EVENT' END,
               CAST(:now AS date) - ((g-1)/1000)::integer - 1, ((g-1)/1000)%10<>0,
               CASE WHEN ((g-1)/1000)%4=0 THEN CAST(:now AS timestamptz) - interval '1 day' ELSE NULL END,
               CAST(:now AS timestamptz) - ((g-1)/1000) * interval '1 day' + interval '29 days'
        FROM generate_series(1,50000) g
    """),
        {"now": now},
    )
    conn.exec_driver_sql("ANALYZE")


def queries(conn: Connection, now: datetime) -> tuple[list[Query], dict]:
    from app.config import NOTI_LIST_LIMIT, PHOTO_LIST_LIMIT, STORY_LOOKBACK_DAYS
    from app.services.weekly import window

    today = datetime.combine(now.date(), time(0), tzinfo=now.tzinfo)
    cursor = conn.execute(
        text("""
        SELECT diary_id, posted_at FROM diaries WHERE room_id=:room AND status='POSTED'
        ORDER BY posted_at DESC, diary_id DESC OFFSET 49 LIMIT 1
    """),
        {"room": ROOM_ID},
    ).one()
    latest = conn.scalar(
        text("""
        SELECT max(fact_date) FROM story_facts WHERE room_id=:room AND is_active
        AND fact_date>=:lookback AND fact_date<:today
    """),
        {"room": ROOM_ID, "lookback": now.date() - timedelta(days=STORY_LOOKBACK_DAYS), "today": now.date()},
    )
    start, end, _ = window(now)
    params = {
        "room": ROOM_ID,
        "user": ROOM_ID,
        "today": today,
        "today_date": now.date(),
        "recent": now.date() - timedelta(days=14),
        "lookback": now.date() - timedelta(days=STORY_LOOKBACK_DAYS),
        "latest": latest,
        "cursor_id": cursor.diary_id,
        "cursor_at": cursor.posted_at,
        "start": start,
        "end": end,
    }
    # routers/diaries.py _rows의 JOIN·정렬·조건. 첫 쪽·다음 쪽은 list_diaries의 limit 51.
    diary_rows = """
        SELECT d.*, u.name, p.object_key, m.nickname FROM diaries d
        LEFT JOIN users u ON u.user_id=d.author_user_id
        LEFT JOIN photos p ON p.photo_id=d.photo_id
        LEFT JOIN room_members m ON m.room_id=d.room_id AND m.user_id=d.author_user_id
        WHERE d.room_id=:room AND d.status='POSTED'
    """
    diary_order = " ORDER BY d.posted_at DESC, d.diary_id DESC"
    # routers/notifications.py _mine. 현재 참여 중인 가족방의 알림만 조회한다.
    mine = """ target_type='FAMILY' AND target_user_id=:user AND room_id IN
        (SELECT room_id FROM room_members WHERE user_id=:user AND removed_at IS NULL) """
    # services/picks.py select_pick의 후보 조회와 후보가 없을 때의 대체 후보.
    usable = (
        "p.room_id=:room AND p.status='ACTIVE' AND p.source='FAMILY' AND p.usable IS NOT FALSE AND p.uploaded_at<:today"
    )
    checks = [
        Query("일기 첫 쪽", diary_rows + diary_order + " LIMIT 51"),
        Query(
            "일기 다음 쪽",
            diary_rows + " AND (d.posted_at<:cursor_at OR "
            "(d.posted_at=:cursor_at AND d.diary_id<:cursor_id))" + diary_order + " LIMIT 51",
        ),
        Query(
            "알림 목록",
            "SELECT * FROM notifications WHERE "
            + mine
            + f" ORDER BY sent_at DESC, notification_id DESC LIMIT {NOTI_LIST_LIMIT}",
        ),
        Query("안 읽은 알림 수", "SELECT count(*) FROM notifications WHERE " + mine + " AND read_at IS NULL"),
        Query(
            "오늘 사진 후보",
            "SELECT p.photo_id FROM photos p WHERE "
            + usable
            + """
            AND p.photo_id NOT IN (SELECT photo_id FROM daily_picks
                WHERE room_id=:room AND pick_date>=:recent AND status='COMPLETED')
        """,
        ),
        Query(
            "오늘 사진 대체 후보",
            """
            SELECT p.photo_id FROM photos p LEFT JOIN
                (SELECT photo_id, max(pick_date) AS done FROM daily_picks
                 WHERE room_id=:room AND status='COMPLETED' GROUP BY photo_id) last_done
            ON last_done.photo_id=p.photo_id WHERE
        """
            + usable
            + " ORDER BY last_done.done ASC NULLS FIRST, p.photo_id LIMIT 1",
        ),
        Query(
            "안 들은 가족 소식",
            diary_rows + " AND d.author_type='FAMILY' AND d.elder_read_at IS NULL" + diary_order + " LIMIT 50",
        ),
        Query(
            "주간 대화",
            """SELECT * FROM sessions WHERE room_id=:room AND started_at>=:start AND started_at<:end
              AND turns @> '[{"speaker":"ELDER"}]'::jsonb""",
        ),
        Query(
            "주간 일기",
            """SELECT * FROM diaries WHERE room_id=:room AND author_type='ELDER' AND status='POSTED'
              AND posted_at>=:start AND posted_at<:end ORDER BY posted_at, diary_id""",
        ),
        Query(
            "오늘 물은 이야기 기억", "SELECT fact_id FROM story_facts WHERE room_id=:room AND used_at>=:today LIMIT 1"
        ),
        Query(
            "최근 이야기 날짜",
            """SELECT max(fact_date) FROM story_facts WHERE room_id=:room AND is_active
              AND fact_date>=:lookback AND fact_date<:today_date""",
        ),
        Query(
            "이야기 기억 선택",
            """SELECT * FROM story_facts WHERE room_id=:room AND fact_date=:latest
              AND is_active AND used_at IS NULL ORDER BY CASE WHEN kind='PLAN' THEN 0 ELSE 1 END, fact_id LIMIT 1""",
        ),
        Query(
            "사진 목록",
            """SELECT * FROM photos WHERE room_id=:room AND status='ACTIVE'
              AND source IN ('FAMILY','ELDER_CAMERA') ORDER BY uploaded_at DESC, photo_id DESC """
            + f"LIMIT {PHOTO_LIST_LIMIT}",
        ),
    ]
    return checks, params


def measure(conn: Connection, query: Query, params: dict) -> tuple[float, bool, str]:
    times = []
    scans, indexes = False, set()
    for attempt in range(4):
        plan = conn.execute(text("EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) " + query.sql), params).scalar_one()[0]
        if attempt:
            times.append(plan["Execution Time"])
        pending = [plan["Plan"]]
        while pending:
            node = pending.pop()
            scans |= node["Node Type"] == "Seq Scan"
            if "Index Name" in node:
                indexes.add(node["Index Name"])
            pending.extend(node.get("Plans", []))
    return median(times), scans, ", ".join(sorted(indexes)) or "없음"


def report(conn: Connection, now: datetime) -> None:
    checks, params = queries(conn, now)
    rows = [(q.name, *measure(conn, q, params)) for q in checks]
    for candidate in CANDIDATES:
        transaction = conn.begin_nested()
        try:
            conn.exec_driver_sql(candidate.ddl)
            conn.exec_driver_sql(f"ANALYZE {candidate.table}")
            rows.extend(
                (q.name + " + " + candidate.name, *measure(conn, q, params))
                for q in checks
                if q.name in candidate.queries
            )
        finally:
            transaction.rollback()
    print("| 조회 | 걸린 ms | Seq Scan | 쓴 인덱스 |")
    print("|---|---:|---|---|")
    for name, milliseconds, seq_scan, indexes in rows:
        print(f"| {name} | {milliseconds:.3f} | {'있음' if seq_scan else '없음'} | {indexes} |")


def main() -> int:
    parser = argparse.ArgumentParser(description="가상 자료를 별도 DB에 생성해 화면 조회 인덱스를 점검합니다.")
    parser.add_argument("--keep", action="store_true", help="시험 DB를 지우지 않고 남깁니다")
    args = parser.parse_args()
    if os.environ.get("APP_ENV") == "deploy":
        print("배포 서버에서는 인덱스 점검을 실행할 수 없어요")
        return 1
    from app.config import now_kst, settings

    if settings.APP_ENV == "deploy":
        print("배포 서버에서는 인덱스 점검을 실행할 수 없어요")
        return 1
    admin = admin_engine(settings.DATABASE_URL)
    engine = None
    created = False
    try:
        with admin.connect() as connection:
            # 같은 시험을 동시에 실행하면 다른 실행의 DB를 지울 수 있어 한 번에 하나만 허용한다.
            if not connection.scalar(text("SELECT pg_try_advisory_lock(20261117, 22)")):
                raise RuntimeError("인덱스 점검이 이미 실행 중이에요")
            try:
                connection.exec_driver_sql(f'DROP DATABASE IF EXISTS "{TEST_DB}"')
                connection.exec_driver_sql(f'CREATE DATABASE "{TEST_DB}"')
                created = True
                engine = create_engine(
                    make_url(settings.DATABASE_URL).set(database=TEST_DB),
                    hide_parameters=True,
                    connect_args={"options": "-c timezone=Asia/Seoul"},
                )
                now = now_kst()
                with engine.begin() as db:
                    populate(db, now)
                with engine.connect() as db:
                    report(db, now)
            finally:
                if engine is not None:
                    engine.dispose()
                if created and not args.keep:
                    connection.exec_driver_sql(f'DROP DATABASE "{TEST_DB}"')
                connection.execute(text("SELECT pg_advisory_unlock(20261117, 22)"))
    finally:
        admin.dispose()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
