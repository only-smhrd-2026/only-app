-- =====================================================================
-- 하루한장 DB 스키마 (PostgreSQL 16) — 테이블 12개. 이 파일이 원천(source of truth)입니다.
-- 바꾸면 backend/app/models.py 도 같이 고칩니다 (PR 템플릿 체크 항목). DB 담당(천주웅·홍진성)이 PR로 수정.
--
-- 기준: 테이블명세서_ONly_최종_1104 의 DDL 원문 + 수정 제안 S1~S15 (개발설계_초석안내서 부록 A).
--       수정한 줄에는 끝에 "-- S번호" 를 달았습니다.
--       11/6 DB 멘토링 반영(D38): 18개 → 12개. 1:1·방당 1개인 표는 칸으로, 대화 턴·출제 기록은 sessions.turns JSON 으로.
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

-- 2. 가족방 (어르신 1명 = 가족방 1개). 초대 링크·어르신 기기도 여기 칸으로 둔다 (D38)
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
    status VARCHAR(10) NOT NULL DEFAULT 'ACTIVE' CHECK (status IN ('ACTIVE', 'CLOSED')),  -- S4 DEFAULT
    -- 초대 링크: 종류마다 살아 있는 링크 1개. 토큰 원문은 저장하지 않고 SHA-256 해시만.
    -- 새로 만들면 덮어써서 이전 링크는 무효. 기기 링크 사용·폐기는 만료 시각을 지금으로 (해시는 남겨 "더 쓸 수 없어요" 안내)
    family_invite_hash CHAR(64) UNIQUE,
    family_invite_expires_at TIMESTAMPTZ,                          -- 발급 + 7일. 기간 안에는 여러 명이 씀
    elder_invite_hash CHAR(64) UNIQUE,
    elder_invite_expires_at TIMESTAMPTZ,                           -- 발급 + 24시간. 1회
    -- 어르신 기기 (계정 없음, 기기 토큰으로 식별). 가족방당 1대 — 새 기기를 연결하면 해시를 덮어써 이전 기기 차단
    device_token_hash CHAR(64) UNIQUE,                             -- NULL = 연결된 기기 없음
    device_push_token VARCHAR(255),
    device_perm_notification BOOLEAN NOT NULL DEFAULT false,
    device_perm_mic BOOLEAN NOT NULL DEFAULT false,                -- S5 DEFAULT
    device_perm_camera BOOLEAN NOT NULL DEFAULT false,             -- S5 DEFAULT
    device_input_mode VARCHAR(8) NOT NULL DEFAULT 'VOICE' CHECK (device_input_mode IN ('VOICE', 'BUTTON')),
    device_connected_at TIMESTAMPTZ,
    device_last_seen_at TIMESTAMPTZ
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

-- 4. 가족방 이름 사전 (STT 힌트·호칭)
CREATE TABLE group_vocab (
    vocab_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    room_id BIGINT NOT NULL REFERENCES family_rooms(room_id),
    term VARCHAR(30) NOT NULL,
    kind VARCHAR(10) NOT NULL CHECK (kind IN ('NAME', 'HONORIFIC', 'PLACE')),
    source VARCHAR(10) NOT NULL CHECK (source IN ('MEMBER', 'UPLOAD', 'SESSION')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_group_vocab_room_id_term UNIQUE (room_id, term)
);

-- 5. 추억 사진 (원본은 R2/로컬 폴더, 여기엔 object_key 만) + AI 분류 (D38). 분류 전에는 분류 칸(usable~analyzed_at)이 NULL
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
    usable BOOLEAN,
    is_old BOOLEAN,
    season VARCHAR(8) CHECK (season IN ('SPRING', 'SUMMER', 'AUTUMN', 'WINTER', 'NONE')),
    activity VARCHAR(20),
    category VARCHAR(20),
    confidence NUMERIC(3,2) CHECK (confidence BETWEEN 0 AND 1),
    corrected_activity VARCHAR(20),
    corrected_at TIMESTAMPTZ,
    model_version VARCHAR(30),
    analyzed_at TIMESTAMPTZ,                                       -- NULL = 아직 분류 전
    CONSTRAINT uq_photos_room_id_object_key UNIQUE (room_id, object_key)   -- S10 업로드 멱등
);
CREATE INDEX ix_photos_room_status ON photos(room_id, status);
CREATE INDEX ix_photos_batch ON photos(upload_batch_id);          -- S14

-- 6. 오늘의 한 장 (가족방·날짜당 1행)
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

-- 7. 대화 세션 (session_id 는 클라이언트가 만든 UUID). 턴·출제 기록은 turns JSON 배열 (D38)
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
    turns JSONB NOT NULL DEFAULT '[]' CHECK (jsonb_typeof(turns) = 'array'),   -- 아래 주석의 키
    CONSTRAINT ck_sessions_turn_count CHECK (turn_count BETWEEN 0 AND 8)   -- 8턴 상한 (R17)
);
-- turns 한 칸 = AI 한 마디 또는 어르신 한 마디 (turn_no 1=AI, 2=ELDER, 3=AI …). 값 없는 키는 넣지 않는다.
-- 칸 안의 값은 DB 가 아니라 서버 코드가 검사한다 (D38).
--   공통  : turn_no, speaker(AI|ELDER), text, created_at
--   어르신: stt_confidence(0~1), input_type(VOICE|CHIP|BUTTON), retried, reply_to_turn_no
--   AI    : question_type(RECALL|REMEMBER|KNOWHOW|THEN_NOW|RECHECK|CLOSING|NONE), latency_ms
--   출제  : question_id(문제 은행 번호, 되짚기는 없음), hint_level(0~3), recheck_result(REMEMBERED|HINTED|SKIPPED|NA),
--           answer_summary — 14일 반복 방지는 최근 14일 세션의 question_id → question_bank 카테고리·활동 (FR-AI-002)
CREATE INDEX ix_sessions_room_started ON sessions(room_id, started_at);   -- S14
CREATE INDEX ix_sessions_pick ON sessions(pick_id);                       -- S14
ALTER TABLE daily_picks
    ADD CONSTRAINT fk_daily_picks_completed_session FOREIGN KEY (completed_session_id) REFERENCES sessions(session_id);  -- S8

-- 8. 문제 은행 (data/question_bank.json 을 seed 가 읽어 넣음). 모든 가족방 공용
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

-- 9. 이야기 기억 (어제 이야기 이어 묻기)
CREATE TABLE story_facts (
    fact_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    room_id BIGINT NOT NULL REFERENCES family_rooms(room_id),
    session_id UUID NOT NULL REFERENCES sessions(session_id),
    source_turn_no SMALLINT NOT NULL,                              -- 근거 턴 = 이 세션 turns 의 turn_no. 없으면 저장 안 함(코드 확인, D38)
    fact_text VARCHAR(200) NOT NULL,
    kind VARCHAR(10) NOT NULL CHECK (kind IN ('EVENT', 'PLAN', 'PREFERENCE', 'CORRECTION')),
    fact_date DATE NOT NULL,                                       -- 한국 날짜 (S15)
    is_active BOOLEAN NOT NULL DEFAULT true,                       -- S2 "그런 말 안 했어" → false (FR-AI-008)
    used_at TIMESTAMPTZ,
    expires_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ix_story_facts_room_date ON story_facts(room_id, fact_date) WHERE is_active;   -- S14 부분 인덱스

-- 10. 일기 (어르신·가족) + 열람 기록 (D38)
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
    elder_read_at TIMESTAMPTZ,                                     -- 어르신 '다 들었어요' (가족 일기). NULL = 안 들음
    family_read_by JSONB NOT NULL DEFAULT '[]' CHECK (jsonb_typeof(family_read_by) = 'array'),  -- '다 봤어요' 누른 가족 user_id 배열
    CONSTRAINT uq_diaries_room_id_request_id UNIQUE (room_id, request_id)   -- S7 가족 일기를 가족방 여러 곳에 게시 가능 (FR-DI-008)
);
CREATE INDEX ix_diaries_room_posted ON diaries(room_id, posted_at DESC);
CREATE INDEX ix_diaries_room_author_posted ON diaries(room_id, author_type, posted_at);   -- S14

-- 11. 주간 이야기 요약 (집계 창: 지난 일요일 19:00 ~ 이번 일요일 19:00 KST, week_start 는 그 주 월요일 날짜)
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

-- 12. 알림 (앱 내)
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
