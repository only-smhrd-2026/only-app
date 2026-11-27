-- 기존 계정 사진을 현재 참여 중인 각 가족방의 시작 사진으로 보존한다.
-- 컬럼 추가와 복사를 한 트랜잭션에서 한 번만 실행해, 재배포로 지운 방 사진이 돌아오지 않게 한다.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_attribute
         WHERE attrelid = 'room_members'::regclass AND attname = 'profile_key' AND NOT attisdropped
    ) THEN
        ALTER TABLE room_members ADD COLUMN profile_key VARCHAR(255);
        UPDATE room_members AS m
           SET profile_key = u.profile_key
          FROM users AS u, family_rooms AS r
         WHERE m.user_id = u.user_id AND m.room_id = r.room_id
           AND m.removed_at IS NULL AND r.status = 'ACTIVE'
           AND u.status = 'ACTIVE' AND u.profile_key IS NOT NULL;
    END IF;
END;
$$;
