-- =====================================================================
-- 하루한장 DB 스키마 (PostgreSQL 16) — 테이블 18개. 이 파일이 원천(source of truth)입니다.
-- 바꾸면 backend/app/models.py 도 같이 고칩니다 (PR 템플릿 체크 항목). DB 담당(천주웅)만 PR로 수정.
--
-- 기준: 테이블명세서_ONly_최종_1104 의 DDL 원문 + 수정 제안 S1~S15 (개발설계_초석안내서 부록 A).
--       수정한 줄에는 끝에 "-- S번호" 를 달았습니다. 11/6 DB 멘토링 결과에 따라 조정합니다.
--
-- S15 시간대: 이 DB의 DATE/TIME 컬럼(pick_date, fact_date, week_start, memory_time, diary_time)은
--       "한국 시간" 의미입니다. 서버가 접속할 때마다 SET timezone='Asia/Seoul' 을 겁니다(backend/app/db.py).
--       SQL 안에서 CURRENT_DATE, now()::date 를 쓰지 않습니다(UTC 날짜가 나올 수 있음). 날짜는 서버가 넘깁니다.
--
-- 적용 방법: backend 폴더에서 `uv run python -m scripts.seed` 가 public 스키마를 비우고
--       이 파일 → db/seed/seed.sql 순서로 실행합니다 (개발 DB 초기화). 생성 순서는 FK 의존 순.
-- =====================================================================

-- 1. 가족 계정
CREATE TABLE users (
    user_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    login_type VARCHAR(10) NOT NULL CHECK (login_type IN ('TEST', 'KAKAO', 'EMAIL')),  -- TEST = 시드로 만든 시연 계정
    email VARCHAR(255) UNIQUE,
    password_hash VARCHAR(255),
    kakao_id VARCHAR(64) UNIQUE,
    name VARCHAR(30) NOT NULL,
    profile_key VARCHAR(255),
    status VARCHAR(10) NOT NULL DEFAULT 'ACTIVE' CHECK (status IN ('ACTIVE', 'WITHDRAWN')),
    terms_agreed_at TIMESTAMPTZ,                                   -- S12 약관 동의 시각 (NFR-AN-004)
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),                 -- S3 DEFAULT 추가
    last_login_at TIMESTAMPTZ
);

-- 2. 가족방 (어르신 1명 = 가족방 1개)
CREATE TABLE family_rooms (
    room_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    elder_name VARCHAR(10) NOT NULL,
    elder_honorific VARCHAR(20) NOT NULL,
    owner_user_id BIGINT NOT NULL REFERENCES users(user_id),       -- 방장 (S13: 여기에만 저장)
    memory_time TIME NOT NULL DEFAULT '09:00',
    diary_time TIME NOT NULL DEFAULT '19:00',
    font_size VARCHAR(5) NOT NULL DEFAULT 'XL' CHECK (font_size IN ('L', 'XL', 'XXL')),
    tts_speed NUMERIC(3,2) NOT NULL DEFAULT 0.85 CHECK (tts_speed IN (0.70, 0.85, 1.00)),
    integration_scope VARCHAR(15) NOT NULL DEFAULT 'NONE' CHECK (integration_scope IN ('NONE', 'SUMMARY_ONLY')),
    integration_consent_at TIMESTAMPTZ,
    external_user_id VARCHAR(64) UNIQUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    status VARCHAR(10) NOT NULL DEFAULT 'ACTIVE' CHECK (status IN ('ACTIVE', 'CLOSED'))   -- S4 DEFAULT
);

-- 3. 가족방 구성원
CREATE TABLE room_members (
    member_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    room_id BIGINT NOT NULL REFERENCES family_rooms(room_id),
    user_id BIGINT NOT NULL REFERENCES users(user_id),
    relation_tag VARCHAR(12) NOT NULL CHECK (relation_tag IN ('CHILD', 'GRANDCHILD', 'OTHER')),
    nickname VARCHAR(12),
    -- S13: is_owner 삭제 (family_rooms.owner_user_id 하나로만 방장 판단)
    joined_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    removed_at TIMESTAMPTZ,                                        -- 내보낸 구성원. NULL 이면 활성
    CONSTRAINT uq_room_members_room_id_user_id UNIQUE (room_id, user_id)
);
CREATE INDEX ix_room_members_user ON room_members(user_id);       -- S14

-- 4. 초대 링크 (토큰 원문은 저장하지 않고 SHA-256 해시만)
CREATE TABLE invites (
    invite_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    room_id BIGINT NOT NULL REFERENCES family_rooms(room_id),
    kind VARCHAR(12) NOT NULL CHECK (kind IN ('ELDER_DEVICE', 'FAMILY')),
    token_hash CHAR(64) NOT NULL UNIQUE,
    expires_at TIMESTAMPTZ NOT NULL,
    used_at TIMESTAMPTZ,
    revoked_at TIMESTAMPTZ,
    created_by BIGINT NOT NULL REFERENCES users(user_id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 5. 어르신 기기 (계정 없음, 기기 토큰으로 식별)
CREATE TABLE elder_devices (
    device_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    room_id BIGINT NOT NULL REFERENCES family_rooms(room_id),
    device_token_hash CHAR(64) NOT NULL UNIQUE,
    push_token VARCHAR(255),
    perm_notification BOOLEAN NOT NULL DEFAULT false,
    perm_mic BOOLEAN NOT NULL DEFAULT false,                       -- S5 DEFAULT
    perm_camera BOOLEAN NOT NULL DEFAULT false,                    -- S5 DEFAULT
    input_mode VARCHAR(8) NOT NULL DEFAULT 'VOICE' CHECK (input_mode IN ('VOICE', 'BUTTON')),
    connected_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen_at TIMESTAMPTZ,
    revoked_at TIMESTAMPTZ
);
CREATE UNIQUE INDEX uq_elder_devices_active_room ON elder_devices(room_id) WHERE revoked_at IS NULL;  -- S14 방당 활성 기기 1

-- 6. 가족방 이름 사전 (STT 힌트·호칭)
CREATE TABLE group_vocab (
    vocab_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    room_id BIGINT NOT NULL REFERENCES family_rooms(room_id),
    term VARCHAR(30) NOT NULL,
    kind VARCHAR(10) NOT NULL CHECK (kind IN ('NAME', 'HONORIFIC', 'PLACE')),
    source VARCHAR(10) NOT NULL CHECK (source IN ('MEMBER', 'UPLOAD', 'SESSION')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_group_vocab_room_id_term UNIQUE (room_id, term)
);

-- 7. 추억 사진 (원본은 R2/로컬 폴더, 여기엔 object_key 만)
CREATE TABLE photos (
    photo_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    room_id BIGINT NOT NULL REFERENCES family_rooms(room_id),
    uploaded_by BIGINT REFERENCES users(user_id),
    upload_batch_id UUID NOT NULL,
    object_key VARCHAR(255) NOT NULL,                              -- 예: rooms/1/<batch uuid>/0.jpg
    thumb_key VARCHAR(255),
    taken_at DATE,
    source VARCHAR(12) NOT NULL CHECK (source IN ('FAMILY', 'ELDER_CAMERA', 'FAMILY_DIARY')),  -- S10 FAMILY_DIARY 추가. 오늘의 한 장 후보는 FAMILY 만
    caption VARCHAR(100),
    people_note VARCHAR(100),
    status VARCHAR(10) NOT NULL DEFAULT 'ACTIVE' CHECK (status IN ('ACTIVE', 'DELETED')),   -- S4 DEFAULT
    uploaded_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_photos_room_id_object_key UNIQUE (room_id, object_key)   -- S10 업로드 멱등
);
CREATE INDEX ix_photos_room_status ON photos(room_id, status);
CREATE INDEX ix_photos_batch ON photos(upload_batch_id);          -- S14

-- 8. 사진 AI 분류
CREATE TABLE photo_meta (
    photo_id BIGINT PRIMARY KEY REFERENCES photos(photo_id),
    usable BOOLEAN NOT NULL,
    is_old BOOLEAN NOT NULL,
    season VARCHAR(8) NOT NULL CHECK (season IN ('SPRING', 'SUMMER', 'AUTUMN', 'WINTER', 'NONE')),
    activity VARCHAR(20) NOT NULL,
    category VARCHAR(20) NOT NULL,
    confidence NUMERIC(3,2) NOT NULL CHECK (confidence BETWEEN 0 AND 1),
    corrected_activity VARCHAR(20),
    corrected_at TIMESTAMPTZ,
    model_version VARCHAR(30) NOT NULL,
    analyzed_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 9. 오늘의 한 장 (가족방·날짜당 1행)
CREATE TABLE daily_picks (
    pick_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    room_id BIGINT NOT NULL REFERENCES family_rooms(room_id),
    pick_date DATE NOT NULL,                                       -- 한국 날짜 (S15)
    photo_id BIGINT NOT NULL REFERENCES photos(photo_id),
    status VARCHAR(10) NOT NULL DEFAULT 'PENDING' CHECK (status IN ('PENDING', 'COMPLETED', 'SKIPPED', 'EXPIRED')),  -- S4 DEFAULT
    shown_count SMALLINT NOT NULL DEFAULT 0,
    completed_at TIMESTAMPTZ,
    skipped_at TIMESTAMPTZ,
    selected_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_session_id UUID,                                     -- S8 완료 세션 (FK는 sessions 생성 뒤 아래에서 추가)
    listened_at TIMESTAMPTZ,                                       -- S8 마무리 낭독 다 들은 시각
    CONSTRAINT uq_daily_picks_room_id_pick_date UNIQUE (room_id, pick_date)
);

-- 10. 대화 세션 (session_id 는 클라이언트가 만든 UUID)
CREATE TABLE sessions (
    session_id UUID PRIMARY KEY,
    room_id BIGINT NOT NULL REFERENCES family_rooms(room_id),
    kind VARCHAR(8) NOT NULL CHECK (kind IN ('MEMORY', 'ALBUM', 'DIARY')),
    pick_id BIGINT REFERENCES daily_picks(pick_id),
    photo_id BIGINT REFERENCES photos(photo_id),
    input_mode VARCHAR(8) NOT NULL CHECK (input_mode IN ('VOICE', 'BUTTON')),
    started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    ended_at TIMESTAMPTZ,
    end_reason VARCHAR(12) CHECK (end_reason IN ('COMPLETED', 'USER_STOP', 'NO_RESPONSE', 'ERROR', 'LIMIT')),
    turn_count SMALLINT NOT NULL DEFAULT 0,
    duration_sec INTEGER,
    emotion_flag VARCHAR(6) NOT NULL DEFAULT 'NONE' CHECK (emotion_flag IN ('NONE', 'SAD')),   -- S4 DEFAULT
    private_flag BOOLEAN NOT NULL DEFAULT false,
    CONSTRAINT ck_sessions_turn_count CHECK (turn_count BETWEEN 0 AND 8)   -- 8턴 상한 (R17)
);
CREATE INDEX ix_sessions_room_started ON sessions(room_id, started_at);   -- S14
CREATE INDEX ix_sessions_pick ON sessions(pick_id);                       -- S14
ALTER TABLE daily_picks
    ADD CONSTRAINT fk_daily_picks_completed_session FOREIGN KEY (completed_session_id) REFERENCES sessions(session_id);  -- S8

-- 11. 세션 턴 (AI 한 마디·어르신 한 마디가 각각 1행, turn_no 는 세션 안 순번)
CREATE TABLE session_turns (
    turn_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    session_id UUID NOT NULL REFERENCES sessions(session_id),
    turn_no SMALLINT NOT NULL,
    speaker VARCHAR(5) NOT NULL CHECK (speaker IN ('AI', 'ELDER')),
    text TEXT NOT NULL,
    stt_confidence NUMERIC(3,2),
    input_type VARCHAR(6) CHECK (input_type IN ('VOICE', 'CHIP', 'BUTTON')),
    retried BOOLEAN NOT NULL DEFAULT false,
    question_type VARCHAR(10) CHECK (question_type IN ('RECALL', 'REMEMBER', 'KNOWHOW', 'THEN_NOW', 'RECHECK', 'CLOSING', 'NONE')),
    reply_to_turn_id BIGINT REFERENCES session_turns(turn_id),
    latency_ms INTEGER,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_session_turns_session_id_turn_no UNIQUE (session_id, turn_no)
);
CREATE INDEX ix_session_turns_session ON session_turns(session_id, turn_no);

-- 12. 문제 은행 (data/question_bank.json 을 seed 가 읽어 넣음)
CREATE TABLE question_bank (
    question_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    qtype VARCHAR(10) NOT NULL CHECK (qtype IN ('REMEMBER', 'KNOWHOW', 'THEN_NOW', 'COMMON')),   -- S1 REMEMBER·KNOWHOW 추가
    activity VARCHAR(20),
    category VARCHAR(20),
    prompt_text VARCHAR(200) NOT NULL,
    choices JSONB,
    priority SMALLINT NOT NULL DEFAULT 5,
    is_active BOOLEAN NOT NULL DEFAULT true,
    created_by VARCHAR(20) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 13. 문제 출제 이력
CREATE TABLE question_history (
    history_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    room_id BIGINT NOT NULL REFERENCES family_rooms(room_id),
    session_id UUID NOT NULL REFERENCES sessions(session_id),
    question_id BIGINT REFERENCES question_bank(question_id),
    qtype VARCHAR(10) NOT NULL CHECK (qtype IN ('REMEMBER', 'KNOWHOW', 'THEN_NOW', 'COMMON', 'RECHECK')),
    asked_turn_id BIGINT NOT NULL REFERENCES session_turns(turn_id),
    answer_summary VARCHAR(200),
    recheck_result VARCHAR(10) CHECK (recheck_result IN ('REMEMBERED', 'HINTED', 'SKIPPED', 'NA')),   -- S6 CHECK 추가
    hint_level SMALLINT NOT NULL DEFAULT 0 CHECK (hint_level BETWEEN 0 AND 3),
    asked_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ix_question_history_room_date ON question_history(room_id, asked_at);

-- 14. 이야기 기억 (어제 이야기 이어 묻기)
CREATE TABLE story_facts (
    fact_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    room_id BIGINT NOT NULL REFERENCES family_rooms(room_id),
    session_id UUID NOT NULL REFERENCES sessions(session_id),
    source_turn_id BIGINT NOT NULL REFERENCES session_turns(turn_id),
    fact_text VARCHAR(200) NOT NULL,
    kind VARCHAR(10) NOT NULL CHECK (kind IN ('EVENT', 'PLAN', 'PREFERENCE', 'CORRECTION')),
    fact_date DATE NOT NULL,                                       -- 한국 날짜 (S15)
    is_active BOOLEAN NOT NULL DEFAULT true,                       -- S2 "그런 말 안 했어" → false (FR-AI-008)
    used_at TIMESTAMPTZ,
    expires_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ix_story_facts_room_date ON story_facts(room_id, fact_date) WHERE is_active;   -- S14 부분 인덱스

-- 15. 일기 (어르신·가족)
CREATE TABLE diaries (
    diary_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    room_id BIGINT NOT NULL REFERENCES family_rooms(room_id),
    author_type VARCHAR(6) NOT NULL CHECK (author_type IN ('ELDER', 'FAMILY')),
    author_user_id BIGINT REFERENCES users(user_id),
    session_id UUID REFERENCES sessions(session_id),
    photo_id BIGINT REFERENCES photos(photo_id),
    body TEXT NOT NULL,
    mood VARCHAR(6) NOT NULL CHECK (mood IN ('SUNNY', 'CLOUDY', 'RAINY', 'MOON')),
    illustration_type VARCHAR(10) NOT NULL CHECK (illustration_type IN ('PHOTO', 'AI_DRAWING', 'NONE')),
    illustration_key VARCHAR(255),
    draw_spec JSONB,
    request_id UUID NOT NULL,                                      -- S7 단독 UNIQUE 해제
    posted_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    status VARCHAR(8) NOT NULL DEFAULT 'POSTED' CHECK (status IN ('POSTED', 'DELETED')),   -- S4 DEFAULT
    CONSTRAINT uq_diaries_room_id_request_id UNIQUE (room_id, request_id)   -- S7 가족 일기를 가족방 여러 곳에 게시 가능 (FR-DI-008)
);
CREATE INDEX ix_diaries_room_posted ON diaries(room_id, posted_at DESC);
CREATE INDEX ix_diaries_room_author_posted ON diaries(room_id, author_type, posted_at);   -- S14

-- 16. 일기 열람 (어르신 열람은 reader_user_id NULL)
CREATE TABLE diary_reads (
    read_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    diary_id BIGINT NOT NULL REFERENCES diaries(diary_id),
    reader_type VARCHAR(6) NOT NULL CHECK (reader_type IN ('ELDER', 'FAMILY')),
    reader_user_id BIGINT REFERENCES users(user_id),
    read_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_diary_reads_diary_id_reader_type_reader_user_id
        UNIQUE NULLS NOT DISTINCT (diary_id, reader_type, reader_user_id)   -- S9 NULL 도 같은 값으로 취급 (PG15+)
);

-- 17. 주간 이야기 요약 (집계 창: 지난 일요일 19:00 ~ 이번 일요일 19:00 KST, week_start 는 그 주 월요일 날짜)
CREATE TABLE weekly_summaries (
    summary_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    room_id BIGINT NOT NULL REFERENCES family_rooms(room_id),
    week_start DATE NOT NULL,                                      -- 한국 날짜 (S15)
    memory_days SMALLINT NOT NULL CHECK (memory_days BETWEEN 0 AND 7),
    diary_days SMALLINT NOT NULL CHECK (diary_days BETWEEN 0 AND 7),
    qa_list JSONB NOT NULL,
    recall_check JSONB NOT NULL,
    mood_trend JSONB NOT NULL,
    talk_volume JSONB NOT NULL,                                    -- 단위: 어절
    diaries JSONB NOT NULL,
    notes JSONB,
    baseline_talk NUMERIC(8,1),                                    -- 첫 4주는 NULL → 추이·경고 생략
    rule_check_passed BOOLEAN NOT NULL,
    generated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    published_at TIMESTAMPTZ,
    model_version VARCHAR(30) NOT NULL,
    CONSTRAINT uq_weekly_summaries_room_id_week_start UNIQUE (room_id, week_start)
);

-- 18. 알림 (앱 내)
CREATE TABLE notifications (
    notification_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    room_id BIGINT NOT NULL REFERENCES family_rooms(room_id),
    target_type VARCHAR(6) NOT NULL CHECK (target_type IN ('ELDER', 'FAMILY')),
    target_user_id BIGINT REFERENCES users(user_id),
    kind VARCHAR(20) NOT NULL CHECK (kind IN (
        'MEMORY_REMINDER', 'DIARY_REMINDER', 'DIARY_POSTED', 'WEEKLY_READY', 'DEVICE_CONNECTED',
        'NO_RECORD_2D', 'PERMISSION_OFF',
        'SESSION_ERROR_3X', 'TTS_ERROR', 'PICK_SKIPPED_2X')),     -- S11 가족 알림 3종 추가
    title VARCHAR(60) NOT NULL,
    body VARCHAR(200),
    link_screen VARCHAR(30),
    sent_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    read_at TIMESTAMPTZ
);
CREATE INDEX ix_notifications_target ON notifications(target_type, target_user_id, read_at);
