# 구조 설명 (ARCHITECTURE)

하루한장 = 하나의 PWA(어르신 화면 + 가족 화면) + FastAPI 서버 + PostgreSQL + 사진 보관함(로컬 폴더 ↔ R2) + AI 부품 4개. 결정의 이유는 [DECISIONS.md](DECISIONS.md).

## 1. 폴더

```
only-app/
├── frontend/                 React 19 + TypeScript + Vite 8 (PWA)
│   └── src/
│       ├── App.tsx           화면 25개 ↔ 경로 표 (파일명 = 화면 ID)
│       ├── api/client.ts     fetch 래퍼 (쿠키 인증, 오류 {detail, code})
│       ├── api/types.ts      서버 응답 타입 (backend/app/schemas 의 거울)
│       ├── hooks/useFetch.ts GET + reload
│       ├── lib/audio.ts      녹음(MediaRecorder)·재생·브라우저 TTS
│       ├── elder.css         어르신 규격 (CSS 변수 10개, 클래스 6개)
│       ├── components/VoiceSession/   말하기 왕복 상태기계 (홍진성)
│       └── screens/elder/*, screens/family/*   화면 (김승희), NotYet.tsx = 준비 중
├── backend/
│   ├── app/main.py           FastAPI 앱, 라우터 등록, lifespan(스케줄러)
│   ├── app/config.py         .env 설정 1곳, 시간대 KST, 상한 상수
│   ├── app/db.py             SQLAlchemy 엔진 (접속마다 timezone=Asia/Seoul)
│   ├── app/models.py         테이블 18개 (db/schema.sql 의 거울)
│   ├── app/deps.py           current_user / current_device / require_member
│   ├── app/security.py       bcrypt, JWT, 토큰 해시, 쿠키, 로그인 속도 제한
│   ├── app/errors.py         오류 형식 {detail, code}
│   ├── app/schemas/          요청·응답 모델 (API 계약)
│   ├── app/routers/          auth, rooms, invites, devices, elder, stt, sessions, media, stubs(빈 API)
│   ├── app/services/         storage(local|r2), picks(오늘의 한 장), scheduler(예약 작업 틀)
│   ├── app/ai/               llm·stt·tts·image 어댑터, coach(회상 코치), schemas(출력 검사), prompts/*.md
│   ├── scripts/seed.py       DB 초기화 + 시드
│   └── tests/                test_auth, test_session_stub, test_tz (docker Postgres 사용)
├── db/schema.sql             테이블 원천 (천주웅만 수정) / db/seed/seed.sql 시드 데이터
├── data/                     question_bank.json, taxonomy.json (박유승), banned_words.json
├── docker-compose.yml        db / --profile deploy: api + caddy
├── Caddyfile                 https, /api → api:8000, 나머지는 화면 정적 파일
└── docs/                     DECISIONS.md, ARCHITECTURE.md
```

## 2. 요청 흐름

### 로그인·권한 (쿠키 2종)

```
가족  POST /api/auth/login ──► Set-Cookie: session=<JWT 7일; HttpOnly; SameSite=Lax>
어르신 POST /api/devices/connect {token} ──► Set-Cookie: device=<기기 토큰 1년>  (서버는 SHA-256 해시만 저장)
모든 요청: deps.current_user → users.status='ACTIVE' / deps.current_device → elder_devices.revoked_at IS NULL
가족방 자원: deps.require_member → room_members.removed_at IS NULL  (내 가족방 것만)
```

### 가족 가입 → 가족방 → 어르신 연결

```
signup → POST /rooms (가족방+구성원) → 사진 3장 이상 → POST /rooms/{id}/invites {kind: ELDER_DEVICE}
  → 링크 http://…/elder/connect#<토큰>  (토큰은 # 뒤라 서버 로그·미리보기에 안 남음)
어르신 폰: 링크 열기 → POST /invites/status {token} → [시작하기] → POST /devices/connect → 마이크 권한
  → PATCH /devices/me/permissions → GET /elder/home
```

### 말하기 한 번 (음성 왕복, 2요청/턴)

```
[말하기] ─녹음(≤60초)─► POST /api/stt (multipart, 메모리에서만 전사 후 폐기)
   ◄─ {transcript, confidence}  → 화면에 전사 표시, [맞아요]/[다시 말할게요], 3초 무조작 확정
[맞아요] ─► POST /api/elder/sessions/{id}/turns {text, input_type:VOICE, stt_confidence, retried}
   서버: ELDER 턴 저장 → coach.next_question(LLM 또는 mock) → 금지어·형식 검사 → AI 턴 저장 → TTS(mock 이면 None)
   ◄─ {ai:{text, audio_b64?, suggestions[], choice_mode, question_type}, state, turn_no, input_locked}
화면: audio_b64 재생 또는 speechSynthesis → 칩 표시 → WAITING(20초 무조작이면 event:NO_RESPONSE)
8번째 답 → AI 마무리(CLOSING) + state:ENDED(COMPLETED) → daily_picks COMPLETED → [다 들었어요] → POST /elder/picks/today/listened
```

서버가 지키는 상한: 8턴(`sessions.turn_count CHECK`), 5분, 무응답 3단계(재질문 → 칩만 → 종료), 저신뢰 2회 → `input_locked`.
화면 타이머: 4초 "조금만 기다려 주세요", 8초 음성 안내, 15초 → `POST /end {reason: ERROR}` (하루 3회면 가족 알림).

### 오늘의 한 장

```
09:00 잡(services/scheduler.select_daily_picks, 천주웅이 채움)  ─┐
GET /elder/home: now ≥ memory_time 이고 오늘 pick 없음 → services/picks.select_pick() ─┴─► INSERT … ON CONFLICT DO NOTHING
후보: ACTIVE + source=FAMILY + 최근 14일 미선정. 건너뛰기: POST /elder/picks/today/skip → SKIPPED
```

### 사진

```
업로드(천주웅): 장당 10MB·30M 픽셀 검사 → EXIF 제거 → JPEG 재인코딩 → storage.put(key)  key=rooms/{room}/{batch}/{i}.jpg
조회: <img src="/api/media/{key}"> → 쿠키로 구성원/기기 확인 → storage.get(key) 바이트 반환 (서명 URL 없음)
STORAGE=local: uploads/ 폴더 (git 제외) / STORAGE=r2: Cloudflare R2 (boto3, R2_* 키)
```

## 3. AI 부품 교체 지점

| 부품 | 파일 | env | mock 동작 | 실제 연결 |
|---|---|---|---|---|
| 회상 대화·요약·분류 | `app/ai/llm.py` `call_json(prompt_name, data, Schema)` | `LLM_PROVIDER=anthropic`, `ANTHROPIC_API_KEY`, `LLM_MODEL` | 고정 질문 7개 순환 | Anthropic SDK, 구조화 출력(JSON 스키마) + pydantic 검사(`app/ai/schemas.py`), 1회 재시도 |
| 음성→글 | `app/ai/stt.py` `transcribe(audio, hints)` | `STT_PROVIDER` | 고정 문장, 0.95 | 담당자가 제공자 분기 추가 (11/15 비교 후) |
| 글→음성 | `app/ai/tts.py` `synthesize(text, speed)` | `TTS_PROVIDER` | None → 브라우저 TTS | mp3 바이트 반환 → 턴 응답 `audio_b64` |
| 그림일기 | `app/ai/image.py` `generate(draw_spec, seed)` | `IMAGE_PROVIDER` | None | Workers AI FLUX.2 klein |

프롬프트는 `app/ai/prompts/*.md`(system). 어르신 말·사진 설명은 JSON **데이터**로만 user 메시지에 넣는다(인젝션 방어). 출력은 코드가 검사: 금지어(`data/banned_words.json`), 물음표 ≤1, 추천 답변 ≤3개×12자.

## 4. 예약 작업·시간대

`services/scheduler.py` — APScheduler(BackgroundScheduler, timezone=Asia/Seoul), 잡 3개(09:00 / 19:00 / 일 19:00)는 빈 함수. 서버·DB 세션·컨테이너 전부 Asia/Seoul(`config.TZ`, `now_kst()`, `today_kst()`; SQL 에서 `CURRENT_DATE` 금지). 놓친 09:00 은 홈 조회가 보정한다.

## 5. 배포

```
폰(https://DOMAIN) ─► caddy(80/443, 인증서 자동, 화면 정적 파일, /api 프록시) ─► api(uvicorn --workers 1) ─► db(postgres:16)
                                                                                 └─ uploads 볼륨 (STORAGE=r2 면 R2)
```
`docker compose --profile deploy up -d --build`. `.env` 에 `APP_ENV=deploy`, 새 `JWT_SECRET`, `DOMAIN` 필수. 개발은 `docker compose up -d db` + `uv run uvicorn` + `npm run dev`(Vite 프록시).
