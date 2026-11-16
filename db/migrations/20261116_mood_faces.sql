-- 11/16 DB 변경 (D75) — 일기 기분을 날씨(맑음·구름·비·달)에서 말(좋았어요·그저 그랬어요·속상했어요·쓸쓸했어요)로.
-- 배포 서버처럼 이미 데이터가 있는 DB 에 1번 돌린다. 두 번 돌려도 안전하다.
-- 새로 만드는 DB(내 PC 의 scripts.seed·테스트)는 schema.sql 이 이미 이 모양이라 돌릴 필요가 없다.
-- 서버(ssh 안, ~/only-app)에서:
--   git pull origin develop
--   docker compose exec -T db sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v ON_ERROR_STOP=1' < db/migrations/20261116_mood_faces.sql
-- 그다음 바로 평소 다시 배포 줄. 옛 코드는 새 값(GOOD 등)을 몰라서, 이 파일과 다시 배포 사이에는 일기 목록·가족 홈 API 가
-- 500 을 낸다(몇십 초). 반대로 다시 배포를 먼저 하면 새 코드가 옛 값(SUNNY 등)을 몰라 같은 일이 생긴다.
-- 옛 값 바꾸기: 맑음 → 좋았어요, 구름 → 그저 그랬어요, 비 → 속상했어요, 달 → 그저 그랬어요
-- (달은 뜻을 정한 적이 없어 '쓸쓸'로 옮기지 않는다 — 가족 카드에 없던 쓸쓸한 날이 생기지 않게).
BEGIN;

ALTER TABLE diaries DROP CONSTRAINT IF EXISTS diaries_mood_check;
UPDATE diaries SET mood = CASE mood
    WHEN 'SUNNY' THEN 'GOOD' WHEN 'CLOUDY' THEN 'SO_SO' WHEN 'RAINY' THEN 'UPSET' WHEN 'MOON' THEN 'SO_SO' ELSE mood END
WHERE mood IN ('SUNNY', 'CLOUDY', 'RAINY', 'MOON');
ALTER TABLE diaries ADD CONSTRAINT diaries_mood_check CHECK (mood IN ('GOOD', 'SO_SO', 'UPSET', 'LONELY'));

-- 주간 이야기 집계에 복사해 둔 기분 (mood_trend·diaries 칸의 "mood": "…")
UPDATE weekly_summaries SET
    mood_trend = replace(replace(replace(replace(mood_trend::text,
        '"SUNNY"', '"GOOD"'), '"CLOUDY"', '"SO_SO"'), '"RAINY"', '"UPSET"'), '"MOON"', '"SO_SO"')::jsonb,
    diaries = replace(replace(replace(replace(diaries::text,
        '"SUNNY"', '"GOOD"'), '"CLOUDY"', '"SO_SO"'), '"RAINY"', '"UPSET"'), '"MOON"', '"SO_SO"')::jsonb
WHERE mood_trend::text ~ '"(SUNNY|CLOUDY|RAINY|MOON)"' OR diaries::text ~ '"(SUNNY|CLOUDY|RAINY|MOON)"';

COMMIT;
