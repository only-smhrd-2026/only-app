-- 11/15 DB 변경 (D74, TEST-01) — 어르신께 들려 드리는 목소리 고르기 + 말 속도 0.80·0.90·1.00(기본 0.90).
-- 배포 서버처럼 이미 데이터가 있는 DB 에 1번 돌린다. 두 번 돌려도 안전하다.
-- 새로 만드는 DB(내 PC 의 scripts.seed·테스트)는 schema.sql 이 이미 이 모양이라 돌릴 필요가 없다.
-- 서버(ssh 안, ~/only-app)에서 다시 배포하기 전에:
--   git pull origin develop
--   docker compose exec -T db sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v ON_ERROR_STOP=1' < db/migrations/20261115_tts_voice.sql
-- 그다음 평소 다시 배포 줄. 순서가 바뀌면 새 코드가 아직 없는 칸(tts_voice)을 읽다가 가족방·어르신 홈 API 가 500 을 낸다.
-- 옛 코드는 tts_voice 를 모르고, 0.90 같은 말 속도도 숫자로 그대로 읽으므로 이 파일을 먼저 돌려도 옛 서버는 그대로 돈다
-- (옛 가족방 설정 API 로는 0.70·0.85 를 다시 고를 수 없게 막힌다 — 새 코드가 뜨면 0.80·0.90·1.00).
BEGIN;

ALTER TABLE family_rooms ADD COLUMN IF NOT EXISTS tts_voice VARCHAR(6) NOT NULL DEFAULT 'FEMALE';
ALTER TABLE family_rooms DROP CONSTRAINT IF EXISTS family_rooms_tts_voice_check;
ALTER TABLE family_rooms ADD CONSTRAINT family_rooms_tts_voice_check CHECK (tts_voice IN ('FEMALE', 'MALE'));

-- 말 속도: 0.70 → 0.80, 0.85 → 0.90 (11/14 밤 사용자 '0.85 너무 느리다, 0.9배로'), 1.00 은 그대로
ALTER TABLE family_rooms DROP CONSTRAINT IF EXISTS family_rooms_tts_speed_check;
UPDATE family_rooms SET tts_speed = 0.80 WHERE tts_speed = 0.70;
UPDATE family_rooms SET tts_speed = 0.90 WHERE tts_speed = 0.85;
ALTER TABLE family_rooms ADD CONSTRAINT family_rooms_tts_speed_check CHECK (tts_speed IN (0.80, 0.90, 1.00));
ALTER TABLE family_rooms ALTER COLUMN tts_speed SET DEFAULT 0.90;

COMMIT;
