-- 11/19 DB 변경 — 웹 푸시 구독 표 push_subscriptions (FR-NT-002·003). 표 하나를 더하기만 한다.
-- 배포 서버처럼 이미 데이터가 있는 DB 에 1번 돌린다. 두 번 돌려도 안전하다(이미 있으면 건너뜀).
-- 새로 만드는 DB(내 PC 의 scripts.seed·테스트)는 schema.sql 이 이미 이 모양이라 돌릴 필요가 없다.
-- 맥에서: ssh … 'cd ~/only-app && bash deploy/redeploy.sh db/migrations/20261119_push_subscriptions.sql'
-- (그 스크립트가 이 파일을 먼저 돌린 뒤 새 코드를 띄운다 — 꼭 그 순서여야 한다.)
-- 옛 코드는 이 표를 몰라서 먼저 돌려도 그대로 돈다. 반대로 이 파일 없이 새 코드만 띄우면, 푸시 키(VAPID)를 안 넣었어도
-- 어르신 기기 연결·연결 해제 API 가 500 을 낸다(옛 기기 구독을 지우려고 이 표를 본다). 키를 넣은 뒤에는 일기 올리기도 이 표를 본다.
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
