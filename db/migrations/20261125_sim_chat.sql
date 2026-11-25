-- 11/25 심심이 잡담 (D106, 사용자 승인 3가지)
--   1. sessions.kind 에 CHAT(심심이 잡담) 추가
--   2. sessions.turn_count 상한 0~8 → 0~30 (잡담 20번 주고받기 + 위로 3번)
--   3. family_rooms.weather_region — 어르신 동네(시·도). 심심이가 날씨를 알려 드릴 때 쓴다. 처음엔 비어 있음(NULL)
-- 배포 서버처럼 이미 데이터가 있는 DB 에 1번 돌린다. 두 번 돌려도 안전하다(IF NOT EXISTS · DROP CONSTRAINT IF EXISTS).
-- 새로 만드는 DB(내 PC 의 scripts.seed·테스트)는 schema.sql 이 이미 이 모양이라 돌릴 필요가 없다.
-- 배포: deploy/redeploy.sh 에 이 파일 경로를 인자로 준다. 옛 코드는 새 값을 쓰지 않으므로 먼저 적용해도 안전하다.
BEGIN;

ALTER TABLE sessions DROP CONSTRAINT IF EXISTS sessions_kind_check;
ALTER TABLE sessions ADD CONSTRAINT sessions_kind_check CHECK (kind IN ('MEMORY', 'ALBUM', 'DIARY', 'CHAT'));

ALTER TABLE sessions DROP CONSTRAINT IF EXISTS ck_sessions_turn_count;
ALTER TABLE sessions ADD CONSTRAINT ck_sessions_turn_count CHECK (turn_count BETWEEN 0 AND 30);

ALTER TABLE family_rooms ADD COLUMN IF NOT EXISTS weather_region VARCHAR(10);

COMMIT;
