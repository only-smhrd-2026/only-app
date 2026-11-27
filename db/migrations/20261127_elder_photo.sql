-- 11/27 어르신 얼굴 사진 (사용자 승인 'family_rooms 에 칸 1개') — 방장만 가족방 탭에서 넣고, 가족 화면 동그라미에 보인다
--   family_rooms.elder_photo_key — 저장소 key rooms/{가족방}/elder/{uuid}.jpg. NULL = 이름 첫 글자 동그라미
-- 배포 서버처럼 이미 데이터가 있는 DB 에 1번 돌린다. 두 번 돌려도 안전하다(IF NOT EXISTS).
-- 새로 만드는 DB(내 PC 의 scripts.seed·테스트)는 schema.sql 이 이미 이 모양이라 돌릴 필요가 없다.
-- 배포: deploy/redeploy.sh 에 이 파일 경로를 인자로 준다. 옛 코드는 새 칸을 쓰지 않으므로 먼저 적용해도 안전하다.
BEGIN;

ALTER TABLE family_rooms ADD COLUMN IF NOT EXISTS elder_photo_key VARCHAR(255);

COMMIT;
