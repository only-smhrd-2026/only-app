-- 11/19 DB 변경 — 웹 푸시 구독 표 push_subscriptions (FR-NT-002·003). 표 하나를 더하기만 한다.
-- 배포 서버처럼 이미 데이터가 있는 DB 에 1번 돌린다. 두 번 돌려도 안전하다(이미 있으면 건너뜀).
-- 새로 만드는 DB(내 PC 의 scripts.seed·테스트)는 schema.sql 이 이미 이 모양이라 돌릴 필요가 없다.
-- 맥에서: ssh … 'cd ~/only-app && bash deploy/redeploy.sh db/migrations/20261119_push_subscriptions.sql'
-- 옛 코드는 이 표를 몰라서 먼저 돌려도 그대로 돈다. 새 코드는 VAPID 키가 .env 에 있을 때만 이 표를 읽는다 —
-- 키를 넣기 전에 이 파일이 먼저 돌아 있어야 한다(위 한 줄이 그 순서다).
-- 아래 CREATE TABLE 은 db/schema.sql 의 것과 글자까지 같다(IF NOT EXISTS 만 다름 — 테스트가 확인).
CREATE TABLE IF NOT EXISTS push_subscriptions (
    subscription_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    room_id BIGINT REFERENCES family_rooms(room_id),
    user_id BIGINT REFERENCES users(user_id),
    endpoint VARCHAR(1000) NOT NULL UNIQUE,                        -- 브라우저 푸시 서비스 주소(FCM·애플·모질라). 허용 목록은 서버 코드가 검사
    p256dh VARCHAR(200) NOT NULL,                                  -- 브라우저 공개 키 (base64url) — 본문 암호화용
    auth VARCHAR(50) NOT NULL,                                     -- 브라우저 인증 비밀 (base64url)
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),                 -- 마지막으로 등록한 때
    CONSTRAINT ck_push_subscriptions_owner CHECK ((room_id IS NULL) <> (user_id IS NULL))
);
