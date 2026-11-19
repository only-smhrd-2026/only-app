-- 11/19 DB 변경 (11/18 멘토링 — 돌봄 루프) — care_days: 가족방·날짜마다 1줄. 전날까지 본 것(숫자) → 판단(평소·지켜봄·주의)
-- → 오늘 첫인사로 여쭐 안부 하나 → 여쭌 시각 → 어르신 답. 어르신 말 원문은 넣지 않는다(숫자와 주제 이름만).
-- 배포 서버처럼 이미 데이터가 있는 DB 에 1번 돌린다. 두 번 돌려도 안전하다(새 테이블 추가만, 기존 테이블은 그대로).
-- 새로 만드는 DB(내 PC 의 scripts.seed·테스트)는 schema.sql 이 이미 이 모양이라 돌릴 필요가 없다.
-- 배포: deploy/redeploy.sh 에 이 파일 경로를 인자로 준다(코드보다 먼저 적용 — 새 코드는 이 테이블을 읽고 쓴다).
BEGIN;

CREATE TABLE IF NOT EXISTS care_days (
    care_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    room_id BIGINT NOT NULL REFERENCES family_rooms(room_id),
    care_date DATE NOT NULL,
    numbers JSONB NOT NULL DEFAULT '{}',
    level VARCHAR(5) NOT NULL CHECK (level IN ('USUAL', 'WATCH', 'CARE')),
    reasons JSONB NOT NULL DEFAULT '[]',
    source VARCHAR(5) CHECK (source IN ('TALK', 'DIARY', 'CHECK')),
    topic VARCHAR(8) CHECK (topic IN ('SLEEP', 'APPETITE', 'LONELY', 'ENERGY', 'INTEREST', 'MOOD')),
    heard_on DATE,
    asked_at TIMESTAMPTZ,
    reaction VARCHAR(4) CHECK (reaction IN ('OK', 'SAME', 'DENY')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_care_days_room_id_care_date UNIQUE (room_id, care_date)
);

COMMIT;
