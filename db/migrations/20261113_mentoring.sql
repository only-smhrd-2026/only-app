-- 11/13 DB 변경 (D57) — 배포 서버처럼 이미 데이터가 있는 DB 에 1번 돌린다. 두 번 돌려도 안전하다.
-- 새로 만드는 DB(내 PC 의 scripts.seed·테스트)는 schema.sql 이 이미 이 모양이라 돌릴 필요가 없다.
-- 서버(ssh 안, ~/only-app)에서 다시 배포하기 전에:
--   git pull origin develop
--   docker compose exec -T db sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v ON_ERROR_STOP=1' < db/migrations/20261113_mentoring.sql
-- 그다음 평소 다시 배포 줄. 순서가 바뀌면 새 코드가 아직 없는 칸을 읽다가 가족방·일기 API 가 500 을 낸다.
-- 옛 코드는 이 칸들을 모르고 SAD·NONE 만 쓰므로, 이 파일을 먼저 돌려도 옛 서버는 그대로 돈다.
BEGIN;

ALTER TABLE family_rooms ADD COLUMN IF NOT EXISTS mood_check_consent_at TIMESTAMPTZ;

ALTER TABLE sessions DROP CONSTRAINT IF EXISTS sessions_emotion_flag_check;
ALTER TABLE sessions ADD CONSTRAINT sessions_emotion_flag_check
    CHECK (emotion_flag IN ('NONE', 'SAD', 'LOW', 'RISK'));

ALTER TABLE diaries ADD COLUMN IF NOT EXISTS reactions JSONB NOT NULL DEFAULT '[]'
    CHECK (jsonb_typeof(reactions) = 'array');

ALTER TABLE notifications DROP CONSTRAINT IF EXISTS notifications_kind_check;
ALTER TABLE notifications ADD CONSTRAINT notifications_kind_check CHECK (kind IN (
    'MEMORY_REMINDER', 'DIARY_REMINDER', 'DIARY_POSTED', 'WEEKLY_READY', 'DEVICE_CONNECTED',
    'NO_RECORD_2D', 'PERMISSION_OFF',
    'SESSION_ERROR_3X', 'TTS_ERROR', 'PICK_SKIPPED_2X',
    'MOOD_URGENT', 'MOOD_LOW_2D'));

CREATE TABLE IF NOT EXISTS mood_checks (
    check_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    room_id BIGINT NOT NULL REFERENCES family_rooms(room_id),
    check_date DATE NOT NULL,
    answers JSONB NOT NULL CHECK (CASE WHEN jsonb_typeof(answers) = 'array' THEN jsonb_array_length(answers) = 8 ELSE false END),
    total SMALLINT NOT NULL CHECK (total BETWEEN 0 AND 24),
    level VARCHAR(5) NOT NULL CHECK (level IN ('USUAL', 'DOWN', 'HARD')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_mood_checks_room_id_check_date UNIQUE (room_id, check_date)
);

COMMIT;
