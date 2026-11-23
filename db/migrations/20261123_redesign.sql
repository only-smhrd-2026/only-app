-- 11/23 DB 변경 (시안 → 앱 옮기기, 사용자 승인 4가지)
--   1. urgent_alerts: 가족이 '안 받으세요'를 누른 사람·시각 (missed_by·missed_at)
--   2. notifications: 누르면 열 것의 번호 link_id(일기 알림 = diary_id) + 종류 ELDER_REPLY·URGENT_MISSED
--   3. users: 폰 알림을 끈 묶음 push_muted (DIARY·WEEKLY·CARE — 급한 알림은 끌 수 없다)
--   4. mood_checks: 종류 kind(PHQ8·PHQ9·UCLA3·GAD7·SMCQ·MEMGAME). answers 칸 수는 서버 코드가, 합 0~27,
--      하루 1줄 → 하루·종류마다 1줄. 이미 있는 줄은 모두 PHQ8(기본값)
-- 배포 서버처럼 이미 데이터가 있는 DB 에 1번 돌린다. 두 번 돌려도 안전하다(IF NOT EXISTS · DROP CONSTRAINT IF EXISTS).
-- 새로 만드는 DB(내 PC 의 scripts.seed·테스트)는 schema.sql 이 이미 이 모양이라 돌릴 필요가 없다.
-- 배포: deploy/redeploy.sh 에 이 파일 경로를 인자로 준다(코드보다 먼저 적용 — 새 코드는 새 칸에 쓴다).
-- 먼저 적용하고 옛 코드가 잠시 도는 동안: 마음 체크 저장(옛 코드의 ON CONFLICT 제약 이름)만 500 이 난다(몇십 초).
BEGIN;

-- 1. urgent_alerts
ALTER TABLE urgent_alerts ADD COLUMN IF NOT EXISTS missed_by BIGINT REFERENCES users(user_id);
ALTER TABLE urgent_alerts ADD COLUMN IF NOT EXISTS missed_at TIMESTAMPTZ;

-- 2. notifications
ALTER TABLE notifications ADD COLUMN IF NOT EXISTS link_id BIGINT;
ALTER TABLE notifications DROP CONSTRAINT IF EXISTS notifications_kind_check;
ALTER TABLE notifications ADD CONSTRAINT notifications_kind_check CHECK (kind IN (
    'MEMORY_REMINDER', 'DIARY_REMINDER', 'DIARY_POSTED', 'WEEKLY_READY', 'DEVICE_CONNECTED',
    'NO_RECORD_2D', 'PERMISSION_OFF',
    'SESSION_ERROR_3X', 'TTS_ERROR', 'PICK_SKIPPED_2X',
    'MOOD_URGENT', 'MOOD_LOW_2D',
    'ELDER_REPLY', 'URGENT_MISSED'));

-- 3. users
ALTER TABLE users ADD COLUMN IF NOT EXISTS push_muted JSONB NOT NULL DEFAULT '[]'
    CHECK (jsonb_typeof(push_muted) = 'array');

-- 4. mood_checks
ALTER TABLE mood_checks ADD COLUMN IF NOT EXISTS kind VARCHAR(8) NOT NULL DEFAULT 'PHQ8'
    CHECK (kind IN ('PHQ8', 'PHQ9', 'UCLA3', 'GAD7', 'SMCQ', 'MEMGAME'));
ALTER TABLE mood_checks DROP CONSTRAINT IF EXISTS mood_checks_answers_check;
ALTER TABLE mood_checks ADD CONSTRAINT mood_checks_answers_check CHECK (jsonb_typeof(answers) = 'array');
ALTER TABLE mood_checks DROP CONSTRAINT IF EXISTS mood_checks_total_check;
ALTER TABLE mood_checks ADD CONSTRAINT mood_checks_total_check CHECK (total BETWEEN 0 AND 27);
ALTER TABLE mood_checks DROP CONSTRAINT IF EXISTS uq_mood_checks_room_id_check_date;
ALTER TABLE mood_checks DROP CONSTRAINT IF EXISTS uq_mood_checks_room_id_check_date_kind;
ALTER TABLE mood_checks ADD CONSTRAINT uq_mood_checks_room_id_check_date_kind UNIQUE (room_id, check_date, kind);

-- 5. photos: 찍은 날(EXIF)이 없는 사진에 가족이 고른 연도 (11/23 사용자 — 스캔·카톡 사진이 '올린 달'로 묶이지 않게)
ALTER TABLE photos ADD COLUMN IF NOT EXISTS taken_year SMALLINT CHECK (taken_year BETWEEN 1900 AND 2100);

COMMIT;
