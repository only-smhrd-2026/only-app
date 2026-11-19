-- 11/19 DB 변경 (응급) — urgent_alerts: 대화에서 감지한 위급(마음 MOOD·몸 BODY) 1건마다 한 줄. 가족 홈 긴급 카드와
-- '[제가 연락했어요]를 누가 눌렀는지', '30분 동안 아무도 안 눌러 한 번 더 알렸는지'를 여기에 적는다.
-- 배포 서버처럼 이미 데이터가 있는 DB 에 1번 돌린다. 두 번 돌려도 안전하다(새 테이블 추가만, 기존 테이블은 그대로).
-- 새로 만드는 DB(내 PC 의 scripts.seed·테스트)는 schema.sql 이 이미 이 모양이라 돌릴 필요가 없다.
-- 배포: deploy/redeploy.sh 에 이 파일 경로를 인자로 준다(코드보다 먼저 적용 — 새 코드는 이 테이블에 쓴다).
BEGIN;

CREATE TABLE IF NOT EXISTS urgent_alerts (
    alert_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    room_id BIGINT NOT NULL REFERENCES family_rooms(room_id),
    session_id UUID REFERENCES sessions(session_id),
    kind VARCHAR(5) NOT NULL CHECK (kind IN ('MOOD', 'BODY')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    acked_by BIGINT REFERENCES users(user_id),
    acked_at TIMESTAMPTZ,
    reminded_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS ix_urgent_alerts_room_created ON urgent_alerts(room_id, created_at);

COMMIT;
