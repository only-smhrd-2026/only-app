-- 11/19 DB 변경 (FR-ME-009) — photos.elder_note·elder_noted_at: 어르신이 회상 대화에서 사진 내용을 바로잡아 주신 한 문장.
-- 배포 서버처럼 이미 데이터가 있는 DB 에 1번 돌린다. 두 번 돌려도 안전하다(추가만, 기존 칸은 그대로).
-- 새로 만드는 DB(내 PC 의 scripts.seed·테스트)는 schema.sql 이 이미 이 모양이라 돌릴 필요가 없다.
-- 배포: deploy/redeploy.sh 에 이 파일 경로를 인자로 준다(코드보다 먼저 적용 — 새 코드는 이 칸을 읽는다).
-- 옛 코드는 이 칸을 모르므로, 이 파일을 먼저 돌려도 옛 서버는 그대로 돈다.
BEGIN;

ALTER TABLE photos ADD COLUMN IF NOT EXISTS elder_note VARCHAR(100);
ALTER TABLE photos ADD COLUMN IF NOT EXISTS elder_noted_at TIMESTAMPTZ;

COMMIT;
