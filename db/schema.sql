-- =====================================================================
-- 하루한장 DB 스키마 (PostgreSQL 16) — 테이블 16개. 이 파일이 원천(source of truth)입니다.
-- 바꾸면 backend/app/models.py 도 같이 고칩니다 (PR 템플릿 체크 항목). DB 담당(천주웅·홍진성)이 PR로 수정.
-- 배포 서버 DB 는 데이터가 있어 seed 로 다시 만들지 않습니다 → 바꾼 만큼 db/migrations/ 에 ALTER 파일을 같은 PR 에 둡니다 (D57).
--
-- 기준: 테이블명세서_ONly_최종_1104 의 DDL 원문 + 수정 제안 S1~S15 (개발설계_초석안내서 부록 A).
--       수정한 줄에는 끝에 "-- S번호" 를 달았습니다.
--       11/6 DB 멘토링 반영(D38): 18개 → 12개. 1:1·방당 1개인 표는 칸으로, 대화 턴·출제 기록은 sessions.turns JSON 으로.
--       11/12 기업 멘토링 반영(D57): 12개 → 13개(mood_checks). diaries.reactions·family_rooms.mood_check_consent_at 칸,
--       sessions.emotion_flag 에 LOW·RISK, notifications.kind 에 마음 알림 2종.
--
-- S15 시간대: 이 DB의 DATE/TIME 컬럼(pick_date, fact_date, week_start, check_date, memory_time, diary_time)은
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
    last_login_at TIMESTAMPTZ,
    -- 폰 알림(웹 푸시)을 끈 묶음 (11/23): 'DIARY' 일기·한마디 · 'WEEKLY' 주간 이야기 · 'CARE' 안부(기운 없는 날·기록 없음).
    -- 급한 알림(MOOD_URGENT·URGENT_MISSED)은 끌 수 없다. 앱 안 알림 목록 줄은 그대로 만들고 푸시만 건너뛴다
    push_muted JSONB NOT NULL DEFAULT '[]' CHECK (jsonb_typeof(push_muted) = 'array')
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
    tts_speed NUMERIC(3,2) NOT NULL DEFAULT 0.90 CHECK (tts_speed IN (0.80, 0.90, 1.00)),   -- D74 (전 0.70·0.85·1.00)
    tts_voice VARCHAR(6) NOT NULL DEFAULT 'FEMALE' CHECK (tts_voice IN ('FEMALE', 'MALE')),  -- D74 어르신이 처음 연결 때 고름
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
    device_last_seen_at TIMESTAMPTZ,
    -- 마음 체크 (D56): 초대에서 '가족에게 한 줄로만 알려요'를 듣고 [할게요]를 누른 첫 시각. NULL = 아직 동의 안 함
    mood_check_consent_at TIMESTAMPTZ
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
    taken_year SMALLINT CHECK (taken_year BETWEEN 1900 AND 2100),  -- 11/23 찍은 날(EXIF)이 없는 사진에 가족이 고른 연도. 있으면 NULL
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
    ai_scene VARCHAR(100),                                         -- 분류 AI 가 본 '보이는 모습' 한 줄, 대화 재료 (D71)
    elder_note VARCHAR(100),                                       -- 어르신이 대화에서 바로잡아 주신 내용 한 문장 (FR-ME-009)
    elder_noted_at TIMESTAMPTZ,
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
    emotion_flag VARCHAR(6) NOT NULL DEFAULT 'NONE' CHECK (emotion_flag IN ('NONE', 'SAD', 'LOW', 'RISK')),   -- S4 DEFAULT. D55: LOW 기운 없는 말, RISK 위급 표현. SAD 는 11/12 전 값
    private_flag BOOLEAN NOT NULL DEFAULT false,
    turns JSONB NOT NULL DEFAULT '[]' CHECK (jsonb_typeof(turns) = 'array'),   -- 아래 주석의 키
    CONSTRAINT ck_sessions_turn_count CHECK (turn_count BETWEEN 0 AND 8)   -- 8턴 상한 (R17)
);
-- turns 한 칸 = AI 한 마디 또는 어르신 한 마디 (turn_no 1=AI, 2=ELDER, 3=AI …). 값 없는 키는 넣지 않는다.
-- 칸 안의 값은 DB 가 아니라 서버 코드가 검사한다 (D38).
--   공통  : turn_no, speaker(AI|ELDER), text, created_at
--   어르신: stt_confidence(0~1), input_type(VOICE|CHIP|BUTTON|TEXT — TEXT 는 글로 쓰기 D52), retried, reply_to_turn_no
--   AI    : question_type(RECALL|REMEMBER|KNOWHOW|THEN_NOW|COMMON|RECHECK|CLOSING|NONE), latency_ms,
--           fact_id(지난 대화의 이야기로 연 첫 질문 — story_facts.fact_id, D77. RECHECK 는 쓰지 않음),
--           urgent(BODY — 몸이 위급하다는 말로 끝난 마무리 턴. 화면이 [119 전화하기]를 띄운다, 11/19),
--           care(오늘의 안부로 연 첫 질문 — care_days.topic, 11/19 돌봄 루프),
--           signal(LOW — 바로 앞 어르신 말을 AI 가 기운 없는 말로 봄. 다음 날 안부 주제를 고르는 데 쓴다)
--   출제  : question_code(문제 은행 code, AI 가 쓴 생각 문제는 'GEN-유형' 예 GEN-REMEMBER — D72, 되짚기는 없음),
--           hint_level(0~3), recheck_result(REMEMBERED|HINTED|SKIPPED|NA),
--           answer_summary — 14일 반복 방지는 최근 14일 세션의 question_code → question_bank.code 의 카테고리·활동,
--           둘 다 없는 문제(그때 vs 지금·공통)는 그 code 자체 (FR-AI-002, D39). 유형 돌리기는 90일 (D72)
CREATE INDEX ix_sessions_room_started ON sessions(room_id, started_at);   -- S14
CREATE INDEX ix_sessions_pick ON sessions(pick_id);                       -- S14
ALTER TABLE daily_picks
    ADD CONSTRAINT fk_daily_picks_completed_session FOREIGN KEY (completed_session_id) REFERENCES sessions(session_id);  -- S8

-- 8. 문제 은행 (data/question_bank.json 을 seed 가 읽어 넣음). 모든 가족방 공용
CREATE TABLE question_bank (
    question_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    code VARCHAR(30) NOT NULL UNIQUE,                              -- 고정 이름표(예 KH-kimjang-01). 출제 기록이 가리키므로 바꾸지 않는다 (D39)
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
    mood VARCHAR(6) NOT NULL CHECK (mood IN ('GOOD', 'SO_SO', 'UPSET', 'LONELY')),   -- D75 좋았어요·그저 그랬어요·속상했어요·쓸쓸했어요
    illustration_type VARCHAR(10) NOT NULL CHECK (illustration_type IN ('PHOTO', 'AI_DRAWING', 'NONE')),
    illustration_key VARCHAR(255),
    draw_spec JSONB,
    request_id UUID NOT NULL,                                      -- S7 단독 UNIQUE 해제
    posted_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    status VARCHAR(8) NOT NULL DEFAULT 'POSTED' CHECK (status IN ('POSTED', 'DELETED')),   -- S4 DEFAULT
    elder_read_at TIMESTAMPTZ,                                     -- 어르신 '다 들었어요' (가족 일기). NULL = 안 들음
    family_read_by JSONB NOT NULL DEFAULT '[]' CHECK (jsonb_typeof(family_read_by) = 'array'),  -- '다 봤어요' 누른 가족 user_id 배열
    reactions JSONB NOT NULL DEFAULT '[]' CHECK (jsonb_typeof(reactions) = 'array'),   -- 리액션 (D54). 키는 아래 주석
    CONSTRAINT uq_diaries_room_id_request_id UNIQUE (room_id, request_id)   -- S7 가족 일기를 가족방 여러 곳에 게시 가능 (FR-DI-008)
);
-- reactions 한 칸 = 한 사람의 리액션 1개. 다른 것을 누르면 그 사람 칸을 바꿔 끼우고, 같은 것을 다시 누르면 지운다(취소, 11/13).
-- 값 없는 키는 넣지 않고, 값은 서버 코드가 검사한다 (D38).
--   by(ELDER|FAMILY), user_id(FAMILY 만), at(누른 시각, turns 의 created_at 과 같은 ISO 문자열),
--   heard_at(FAMILY 칸만 — 어르신이 가족 소식 첫 장에서 들은 시각, 같은 ISO 문자열. 없으면 아직 못 들으심, D63),
--   kind: LIKE = 어르신 [좋아요] (가족 일기에) | HEART·SMILE·CLAP = 가족 이모지 (어르신 일기에)
--         REPLY = 가족 한마디 (어르신 일기에, 11/19) — text(한 줄 1~40자) 키가 더 있다. 이모지 칸과 따로 한 사람 1칸, 글을 바꾸면 새 칸
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
        'SESSION_ERROR_3X', 'TTS_ERROR', 'PICK_SKIPPED_2X',       -- S11 가족 알림 3종 추가
        'MOOD_URGENT', 'MOOD_LOW_2D',                             -- D55 마음 알림: 위급 표현 1번 → 바로, 기운 없는 날 7일 중 2일 → 주 1건
        'ELDER_REPLY', 'URGENT_MISSED')),                         -- 11/23 어르신 말로 답하기 · 급한 알림 '안 받으세요'
    title VARCHAR(60) NOT NULL,
    body VARCHAR(200),
    link_screen VARCHAR(30),
    link_id BIGINT,                                                -- 11/23 누르면 열 것의 번호. 일기 알림(DIARY_POSTED·ELDER_REPLY) = diary_id
    sent_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    read_at TIMESTAMPTZ
);
CREATE INDEX ix_notifications_target ON notifications(target_type, target_user_id, read_at);

-- 13. 마음 체크 결과 (D56: PHQ-9 에서 9번을 뺀 8문항, 2주에 한 번 → 11/23 '내 마음' 체크 5가지 + 기억력 놀이).
--     어르신이 끝까지 답했을 때만 1줄, 가족방·날짜·종류마다 1줄
CREATE TABLE mood_checks (
    check_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    room_id BIGINT NOT NULL REFERENCES family_rooms(room_id),
    check_date DATE NOT NULL,                                      -- 한국 날짜 (S15)
    -- 11/23 종류: PHQ8 마음 체크(기본·2주에 한 번) · PHQ9 자세히 · UCLA3 외로움 · GAD7 걱정 · SMCQ 기억력 · MEMGAME 기억력 놀이.
    -- 가족 홈(마음 카드·돌봄 일지·주간 이야기)에는 PHQ8·PHQ9 만 쓴다
    kind VARCHAR(8) NOT NULL DEFAULT 'PHQ8' CHECK (kind IN ('PHQ8', 'PHQ9', 'UCLA3', 'GAD7', 'SMCQ', 'MEMGAME')),
    -- 문항 순서대로 화면이 보낸 값. 배열인지만 DB 가, 종류별 칸 수·값 범위는 서버 코드가 검사(schemas/mood.py)
    answers JSONB NOT NULL CHECK (jsonb_typeof(answers) = 'array'),
    total SMALLINT NOT NULL CHECK (total BETWEEN 0 AND 27),        -- 공식 채점 합(PHQ9 최대 27). 화면에 점수를 보이지 않는다 (NFR-DE-003)
    -- 가족 홈 문장: USUAL 평소와 비슷해요 / DOWN 조금 가라앉으신 편이에요 / HARD 많이 힘드신 것 같아요(상담 권유).
    -- 합 구간은 config 상수(마음 체크 API 때). 단계를 저장해 기준이 바뀌어도 옛 결과의 뜻이 남는다
    level VARCHAR(5) NOT NULL CHECK (level IN ('USUAL', 'DOWN', 'HARD')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_mood_checks_room_id_check_date_kind UNIQUE (room_id, check_date, kind)   -- 같은 날 같은 종류를 두 번 보내도 1줄
);

-- 14. 웹 푸시 구독 (11/19, FR-NT-002·003). 한 줄 = 알림을 받는 브라우저 하나.
--     어르신 기기는 room_id(가족방당 1줄 — 새 기기 연결·해제 때 지움), 가족은 user_id(쓰는 브라우저마다 1줄).
--     같은 브라우저(endpoint)가 다시 등록하면 그 줄의 주인을 바꾼다. family_rooms.device_push_token 은 쓰지 않는다.
CREATE TABLE push_subscriptions (
    subscription_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    room_id BIGINT REFERENCES family_rooms(room_id),
    user_id BIGINT REFERENCES users(user_id),
    endpoint VARCHAR(1000) NOT NULL UNIQUE,                        -- 브라우저 푸시 서비스 주소(FCM·애플·모질라). 허용 목록은 서버 코드가 검사
    p256dh VARCHAR(200) NOT NULL,                                  -- 브라우저 공개 키 (base64url) — 본문 암호화용
    auth VARCHAR(50) NOT NULL,                                     -- 브라우저 인증 비밀 (base64url)
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),                 -- 마지막으로 등록한 때
    CONSTRAINT ck_push_subscriptions_owner CHECK ((room_id IS NULL) <> (user_id IS NULL))
);

-- 15. 위급 알림 (D55 마음 위급 + 11/19 몸 위급). 대화에서 감지한 위급 1건마다 한 줄 — 가족 홈 긴급 카드
CREATE TABLE urgent_alerts (
    alert_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    room_id BIGINT NOT NULL REFERENCES family_rooms(room_id),
    session_id UUID REFERENCES sessions(session_id),               -- 어느 대화에서 감지했는지
    kind VARCHAR(5) NOT NULL CHECK (kind IN ('MOOD', 'BODY')),      -- MOOD 마음 위급(RISK), BODY 몸 위급
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    acked_by BIGINT REFERENCES users(user_id),                     -- [제가 연락했어요]를 처음 누른 가족
    acked_at TIMESTAMPTZ,
    reminded_at TIMESTAMPTZ,                                       -- 30분 동안 확인이 없어 한 번 더 알린 시각
    -- 11/23 가족이 전화했는데 '안 받으세요'를 누름 → 다른 가족에게 알림(URGENT_MISSED). 카드는 확인 안 된 채 남는다
    missed_by BIGINT REFERENCES users(user_id),
    missed_at TIMESTAMPTZ
);
CREATE INDEX ix_urgent_alerts_room_created ON urgent_alerts(room_id, created_at);

-- 16. 돌봄 일지 (11/18 멘토링 — 돌봄 루프). 가족방·날짜마다 1줄: 전날까지 본 것 → 판단 → 오늘 여쭐 안부 → 어르신 답.
-- 어르신 말 원문은 넣지 않는다(숫자와 주제 이름만). 보관 CARE_KEEP_DAYS 일 — 줄을 만들 때 오래된 줄을 지운다
CREATE TABLE care_days (
    care_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    room_id BIGINT NOT NULL REFERENCES family_rooms(room_id),
    care_date DATE NOT NULL,                                       -- 이 줄이 쓰이는 날(한국 날짜). 전날까지의 기록으로 만든다
    -- 전날 숫자: talks·turns·words·avg_words·chip_ratio·stopped·low·diary_mood (서버 코드가 채운다, services/care.py)
    numbers JSONB NOT NULL DEFAULT '{}',
    level VARCHAR(5) NOT NULL CHECK (level IN ('USUAL', 'WATCH', 'CARE')),   -- 평소 / 지켜봄 / 주의. 코드가 정한다(AI 아님)
    reasons JSONB NOT NULL DEFAULT '[]',                           -- 그렇게 본 이유: LOW_TALK·DIARY_MOOD·TALK_DOWN·QUIET·CHECK_ITEM·SAME_AGAIN
    source VARCHAR(5) CHECK (source IN ('TALK', 'DIARY', 'CHECK')),          -- 오늘 안부가 나온 곳: 대화의 말 / 일기 기분 / 마음 체크 문항
    topic VARCHAR(8) CHECK (topic IN ('SLEEP', 'APPETITE', 'LONELY', 'ENERGY', 'INTEREST', 'MOOD')),   -- NULL = 여쭐 안부 없음
    heard_on DATE,                                                 -- 그 말을 들은 날 — 첫인사의 '어제·며칠 전'
    asked_at TIMESTAMPTZ,                                          -- 그 안부를 실제로 여쭌 시각 (그날 첫 회상 대화)
    reaction VARCHAR(4) CHECK (reaction IN ('OK', 'SAME', 'DENY')),          -- 어르신 답: 괜찮다 / 여전하다 / 그런 적 없다
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_care_days_room_id_care_date UNIQUE (room_id, care_date)
);
