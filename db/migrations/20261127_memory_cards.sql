-- 11/27 팀 회의 — 회상 카드 (D115, 사용자 승인 'sessions 에 요약+반응 칸 2개')
--   1. sessions.family_summary — 회상 대화가 끝나면 AI 가 만든 가족용 한두 줄 요약 (NULL 아직, '' 만들지 않음)
--   2. sessions.reactions — 회상 카드의 가족 좋아요·댓글 (diaries.reactions 와 같은 칸 모양)
-- 배포 서버처럼 이미 데이터가 있는 DB 에 1번 돌린다. 두 번 돌려도 안전하다(IF NOT EXISTS).
-- 새로 만드는 DB(내 PC 의 scripts.seed·테스트)는 schema.sql 이 이미 이 모양이라 돌릴 필요가 없다.
-- 배포: deploy/redeploy.sh 에 이 파일 경로를 인자로 준다. 옛 코드는 새 칸을 쓰지 않으므로 먼저 적용해도 안전하다.
-- 예전 회상 대화는 NULL 로 남는다 — 요약 작업은 최근 하루 안의 대화만 만든다.
BEGIN;

ALTER TABLE sessions ADD COLUMN IF NOT EXISTS family_summary VARCHAR(200);
ALTER TABLE sessions ADD COLUMN IF NOT EXISTS reactions JSONB NOT NULL DEFAULT '[]'
    CHECK (jsonb_typeof(reactions) = 'array');

COMMIT;
