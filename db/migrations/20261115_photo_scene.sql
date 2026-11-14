-- 11/15 DB 변경 (D71) — photos.ai_scene: 사진 분류 AI 가 본 '보이는 모습' 한 줄(대화 재료).
-- 배포 서버처럼 이미 데이터가 있는 DB 에 1번 돌린다. 두 번 돌려도 안전하다.
-- 새로 만드는 DB(내 PC 의 scripts.seed·테스트)는 schema.sql 이 이미 이 모양이라 돌릴 필요가 없다.
-- 서버(ssh 안, ~/only-app)에서 다시 배포하기 전에:
--   git pull origin develop
--   docker compose exec -T db sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v ON_ERROR_STOP=1' < db/migrations/20261115_photo_scene.sql
-- 그다음 평소 다시 배포 줄. 순서가 바뀌면 새 코드가 아직 없는 칸을 읽다가 사진·대화 API 가 500 을 낸다.
-- 옛 코드는 이 칸을 모르므로, 이 파일을 먼저 돌려도 옛 서버는 그대로 돈다.
BEGIN;

ALTER TABLE photos ADD COLUMN IF NOT EXISTS ai_scene VARCHAR(100);

COMMIT;
