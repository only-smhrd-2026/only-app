# 기술 결정 기록 (DECISIONS)

하루한장 뼈대(초석)에서 정한 것들을 **이유 / 대안 / 트레이드오프**와 함께 적는다. 발표·면접에서 "왜 이렇게 했나"에 답하는 원천.
결정을 바꾸면 여기 줄을 고치고 PR 에 `D번호` 를 적는다. 원천 문서: 설계안 v1(2026-11-04), 11/5 팀 회의.

## 0. 전제

React PWA(TypeScript) / Python 3.12 + FastAPI / PostgreSQL 16(테이블 18) / Cloudflare R2 / APScheduler / Claude Haiku 5.5 / STT·TTS 는 11/15 비교 후 확정 / EC2 + Docker Compose + Caddy. 키는 Anthropic 만 있음 → 나머지는 mock. 구현 11/9~12/4, 중간 점검 11/22.

**11/5 팀 회의 결정**: 초석 범위는 원안(음성 왕복 걷는 해골 + VoiceSession + 실제 화면 6개 포함). 공통 사진(계절·명절 20장)은 MVP 제외(테이블 없음, FR-ME-005 80/20 문구 수정). 테이블 수정 S1~S15 를 `db/schema.sql` 에 지금 반영.

## 1. 결정 표

| # | 결정 | 이유 | 대안 | 트레이드오프 |
|---|---|---|---|---|
| D1 | `db/schema.sql` 이 원천, `models.py` 는 거울, Alembic 없음 | README 약속(DB 담당이 schema.sql PR), 테이블명세서가 산출물, 12/15 전 보존할 운영 데이터 없음 | Alembic / automap | 바꿀 때 두 곳 수정(PR 체크박스). 운영 데이터 보존이 필요해지면 Alembic |
| D2 | **인증 = HttpOnly 쿠키** 2종: 가족 `session`(JWT HS256, sub·exp, 7일), 어르신 `device`(기기 토큰 원문, 1년; 서버는 SHA-256 해시만). `HttpOnly; SameSite=Lax`, 변경 API 는 전부 POST/PATCH/DELETE + JSON → CSRF 차단. 어르신 PWA 는 연결 직후 `navigator.storage.persist()` | `<img>`·`<audio>` 가 헤더를 못 보내서 생기는 서명 URL·만료 갱신 코드가 통째로 사라짐. XSS 로 토큰 유출 면적 감소. 단일 오리진(D7) 전제 | Bearer 헤더 + localStorage + 서명 미디어 URL | 브라우저 프로필에 묶임(curl 테스트는 쿠키 jar). 즉시 차단은 매 요청 DB 확인: `users.status='ACTIVE'`, `room_members.removed_at IS NULL`, `elder_devices.revoked_at IS NULL` |
| D3 | 동기 SQLAlchemy 2.0 + FastAPI `def` 엔드포인트 + 동기 외부 클라이언트 | 주니어 팀, async 함정 제거, 시연 규모 | async + httpx | 동시 100명↑이면 스레드풀 포화. bcrypt rounds 10 으로 CPU 점유 완화 |
| D4 | 어댑터 4개(`ai/stt.py`·`tts.py`·`llm.py`·`image.py`) 각 1파일 + `*_PROVIDER` env, 기본 mock. 시그니처 고정: `transcribe(audio, hints) -> (text, confidence)`, `synthesize(text, speed) -> bytes|None`, `call_json(prompt_name, data, Schema) -> Schema`, `generate(draw_spec, seed) -> bytes|None`. 호출당 `provider, ms, tokens` 로그 1줄 | 키가 Anthropic 뿐, 교체 지점(NFR-DE-004), 원가 실측(NFR-AN-003) | — | mock 품질 검증 불가 |
| D5 | 음성 대체 경로 2단: (a) 세션 내 저신뢰 2회 → `input_locked=true` → 그 세션은 칩·버튼만 (b) STT 미설정/장애 → 브라우저 `SpeechRecognition`(TODO). TTS 실패 → 자막만 + 가족 알림 `TTS_ERROR` 1건. 서버 TTS 가 없으면(mock) 브라우저 `speechSynthesis` | FR-VS-006 | — | 브라우저 TTS 음색 차이. (a) 는 서버(확인 질문 2회)와 화면([다시 말할게요] 2회) 양쪽에서 지킴 |
| D6 | **음성 왕복 = 2요청/턴**: `POST /api/stt` → 전사 표시·확정 → `POST …/turns`. TTS 오디오는 턴 응답에 base64 인라인(저장·URL 없음) | FR-VS-002 "전사 2초 안에 표시 → [맞아요]/[다시 말할게요]" 뒤에 LLM. 확인 전에 LLM 을 부르면 잘못 들은 말로 흐르고 비용 낭비 | 1요청, WebSocket | 왕복 1회 추가(확정 창 안이라 체감 없음) |
| D7 | 단일 오리진. 개발: Vite 프록시 `/api→8000`(`changeOrigin:false` 로 Host 유지 → 초대 링크가 화면 주소로 생성), CORS 없음. 배포: **caddy → api → db** 컨테이너 3개, Caddyfile `{$DOMAIN} { reverse_proxy api:8000 }`(Let's Encrypt), 경로별 `request_body max_size`(업로드 220MB, 나머지 5MB), uvicorn `--proxy-headers --forwarded-allow-ips='*'`. 화면 정적 파일은 Caddy `file_server`(frontend/Dockerfile 멀티스테이지) | HTTPS 만(NFR-DV-004), getUserMedia·PWA 설치는 secure context 필수 | nginx+certbot, cloudflared, FastAPI StaticFiles | 도메인 1개 필요(DuckDNS 가능). 실기기 로컬 테스트는 `adb reverse` 후 `http://localhost:5173`(localhost 는 secure context) |
| D8 | 상한값은 config 상수(`MAX_TURNS=8, MAX_SESSION_SEC=300, ALBUM_PER_DAY=3, ELDER_PUSH_PER_DAY=2`) | 설정 테이블이 명세에 없음 | app_settings 테이블 | 런타임 변경 불가. NFR-DV-006 문구 수정(PM) |
| D9 | APScheduler in-process(timezone=KST) + **지연 보정**: `GET /api/elder/home` 에서 `now ≥ memory_time ∧ 오늘 pick 없음 → select_pick()`(`INSERT … ON CONFLICT DO NOTHING`). 주간 요약은 lifespan `catch_up()`. compose `restart: unless-stopped`, uvicorn `--workers 1` | FR-ME-005 "그때 정하지 못했으면 다음 조회 때", 재시작 시 잡 유실 | Celery/cron, 영속 잡스토어 | 수평 확장 불가(불필요) |
| D10 | 프론트: CSS 변수 10개 + 클래스(`elder.css`), fetch 래퍼 + `useFetch`. Tailwind·react-query 없음 | 어르신 규격이 고정값, 25화면 대부분 조회·게시 | Tailwind v4, react-query | FE 가 원하면 첫 PR 에서 추가 |
| D11 | 파일명 = 화면 ID(`ELDER_HOME_001.tsx`), 라우트 표 1곳(`App.tsx`), 미구현은 `NotYet` | 지침·화면설계서 규칙 | PascalCase | 화면설계서 `.jsx` 예시 → `.tsx` 문서 수정 |
| D12 | **시간대 Asia/Seoul 1곳 고정**: `config.TZ`, `now_kst()/today_kst()`; `create_engine(connect_args={"options":"-c timezone=Asia/Seoul"})`; `BackgroundScheduler(timezone=TZ)`; compose `TZ`; ruff `DTZ`; `tests/test_tz.py`. SQL 의 `CURRENT_DATE`·`now()::date` 금지 | DATE/TIME 컬럼이 로컬 의미. EC2·컨테이너·GitHub 러너는 UTC | 가족방별 timezone 컬럼 | 국내 서비스라 불필요 |
| D13 | 비동기 작업(분류·그림·주간)은 FastAPI `BackgroundTasks`(in-process) | 단일 프로세스(D9) | 큐 | 재시작 시 유실 → 분류는 `photo_meta` 없는 사진을 다음 요청·잡에서 재시도 |
| D14 | LLM 경계: 지시는 system(`ai/prompts/*.md`)에만, 데이터는 `json.dumps(…, ensure_ascii=False)` 로 user 메시지에(구분자 없음). JSON 스키마로 출력 강제 + pydantic `field_validator` 로 금지어·물음표 ≤1·suggestions ≤3×≤12자. 실패 1회 재시도, 재실패 시 고정 문장. `effort: low` + `max_tokens 400` | 구분자는 자유 텍스트로 위조 가능. 금지어는 모든 어르신 턴에 적용(NFR-DE-003) | `<data>` 구분자 | 분류 프롬프트는 enum+none 출력이라 인젝션 피해가 오분류로 한정 |
| D15 | 로그 위생: ValidationError 는 `prompt_name, attempt, len(raw)` 만, 전역 예외 핸들러는 경로·예외 타입만, 전사·토큰을 쿼리스트링에 넣지 않음, 오디오는 메모리에서만 | 500 트레이스백에 전사 유출 방지(NFR-AN-001) | — | 디버깅은 로컬에서만 |
| D16 | 초대 토큰은 항상 **본문**으로: `POST /api/invites/status {token}`, `POST /api/invites/accept {token}`, `POST /api/devices/connect {token}`. 소모는 `UPDATE … WHERE used_at IS NULL AND revoked_at IS NULL AND expires_at>now() RETURNING` 한 문장. SPA 링크는 `/join#<token>`·`/elder/connect#<token>`(프래그먼트는 서버 로그·Referer·미리보기 봇에 안 감 — 카톡 `#` 보존은 11/9 주 실기기 확인). 방당 활성 기기 1·활성 기기 링크 1(새 발급·연결 시 기존 폐기). 내보낸 구성원은 같은 링크로 재가입 403 | 1회 링크가 미리보기 봇에 소모되는 것, 동시 탭 2회 통과 방지. (v1 계약의 `GET /status?token=` 은 D15 와 충돌해 POST 로 바꿈) | 경로/쿼리 파라미터 | — |
| D17 | 업로드(천주웅 PR 규칙): `UploadFile.size ≤ 10MB` 장당 검사, `Image.open` 직후 `width*height ≤ 30M`, 배치 순차 처리, `exif_transpose` 후 항상 JPEG 재인코딩만 저장(원본 미보관 → EXIF·GPS 자동 탈락), 허용 JPEG/PNG/HEIC(`pillow-heif`), 클라 content_type·파일명 무시, key = `rooms/{room_id}/{upload_batch_id}/{index}.jpg`, `UNIQUE(room_id, object_key)` 멱등 | 이미지 폭탄·OOM(t4g.small 2GB) | — | — |
| D18 | 로컬 미디어: key `^rooms/\d+/[0-9a-f-]{36}(/\d+)?\.jpg$` + `Path(base,key).resolve().is_relative_to(base)`, room_id 는 photos 행에서. 권한 없음도 404 | 경로 탐색, 존재 여부 비노출 | — | — |
| D19 | 주간 집계 창 = [지난 일요일 19:00, 이번 일요일 19:00) KST, `week_start` 는 그 주 월요일. baseline_talk NULL(첫 4주)이면 추이·경고 생략. 말한 양 단위 = 어절 | 일요일 19:00~24:00 누락 방지 | 월요일 00:30 생성 | 가족 약속 "일요일 저녁 도착" 유지 |
| D20 | 로그인 IP 당 10회/분 메모리 카운터, 실패 문구 동일, `JWT_SECRET` 32자 미만이면 기동 거부, `algorithms=["HS256"]` 고정 | 무차별 대입, alg 혼동 | — | 재시작 시 카운터 초기화(무방) |

## 2. 구현하면서 추가한 결정 (11/5)

| # | 결정 | 이유 | 대안 | 트레이드오프 |
|---|---|---|---|---|
| D21 | `.env.example` 만 복사하면 값 없이 실행: 개발 기본값(DB `only/only`, `JWT_SECRET` 48자 개발값). `APP_ENV=deploy` 에서 개발 기본값 그대로면 기동 거부. `.env` 의 빈 값(`KEY=`)은 기본값으로(`env_ignore_empty`) | 안내서 약속 "값 없이 mock 실행" 과 D20 의 절충 | 기동 시 무조건 거부 | 배포 전에 `.env` 를 꼭 바꿔야 함(README 배포 절) |
| D22 | 쿠키 `Secure` 는 dev(`APP_ENV=dev`)에서만 끔 | Safari 가 `http://localhost` 의 Secure 쿠키를 거부 | 항상 켬 | 배포는 항상 Secure(Caddy https) |
| D23 | PWA 는 플러그인 없이 `public/manifest.webmanifest` + 최소 `sw.js`(껍데기만 네트워크 우선 캐시, `/api` 미캐시). `start_url=/elder` | Vite 8 과 플러그인 호환 불확실, 필요한 건 설치 가능성뿐 | vite-plugin-pwa | 오프라인 동작 없음(필요 없음) |
| D24 | 시드: `scripts/seed.py` 가 public 스키마 초기화 → `schema.sql` → `db/seed/seed.sql` → 사진 3장 생성(Pillow) → `question_bank.json` → 오늘의 한 장. 어르신 기기 링크는 1회용(만료 2030) — 다시 쓰려면 시드 재실행 | 명령 1개로 같은 상태, 이진 파일 커밋 없음 | docker-entrypoint-initdb.d | 시드는 기존 데이터를 지움(`deploy` 는 `--force`) |
| D25 | 이메일은 정규식만 검사(`email-validator` 미사용) | 메일을 보내지 않음. validator 가 `.local` 같은 테스트 도메인을 거부 | pydantic `EmailStr` | 오타 메일도 가입됨(무방) |
| D26 | 세션별 카운터(무응답 단계·저신뢰 횟수·마지막 AI 칩)는 프로세스 메모리 | 워커 1개(D9), 세션은 30분 뒤 ENDED 취급 | sessions 테이블 컬럼 | 재시작 시 초기화. 수평 확장 시 컬럼으로 옮김 |
| D27 | 오늘의 한 장 완료 기록은 `/end` 의 reason 이 `ERROR` 가 아닐 때만(COMPLETED·USER_STOP·LIMIT·NO_RESPONSE). ERROR 는 PENDING 유지, 하루 3회면 `SESSION_ERROR_3X` 알림 | 오류로 끝난 날의 대화 기회를 잃지 않게 | 모든 종료에 완료 | 같은 날 다시 시도 가능 |
| D28 | 테스트는 docker Postgres 의 `only_app_test` DB 에 `schema.sql` 을 그대로 적용(SQLite 대체 없음) | PG 전용 문법(부분 인덱스, `NULLS NOT DISTINCT`, JSONB) 검증, D1 유지 | SQLite | `docker compose up -d db` 가 선행 |
| D29 | DB 호스트 포트는 `DB_PORT`(기본 5432) | 내 PC 에 Postgres 가 이미 있으면 충돌 | 고정 5432 | 두 값(`DB_PORT`, `DATABASE_URL`)을 같이 바꿔야 함 |
| D30 | LLM 실호출은 `anthropic` SDK `messages.create` + `output_config.format(json_schema)`, 모델 `claude-haiku-5-5`, `effort: low` | 구조화 출력으로 JSON 파싱 실패 제거, 비용 | tool_use 강제 | 스키마 제약 키 일부 제거(`_simplify`) 후 pydantic 이 재검사 |
| D31 | 5분 상한 = **대화한 시간**: 시작·각 턴·지금 사이 간격을 90초(`PAUSE_GAP_SEC`)까지만 더한다. 마지막 턴 뒤 30분이면 GET·POST 모두 끝난 대화(POST 는 NO_RESPONSE 로 닫고 409). 5분에 걸린 턴은 어르신 답을 먼저 저장하고 마무리 | 시작 시각 기준이면 '보류 30분 복귀'(FR-VS-004)가 불가능. 턴 시각이 이미 DB 에 있어 컬럼 추가 없음 | `sessions.paused_at` 컬럼(DB 담당 PR) | 90초 넘는 침묵은 보류로 간주(무응답 3단계 60초 + 여유) |
| D32 | 처리 못 한 예외는 `exception_handler(Exception)` 대신 HTTP 미들웨어에서 삼켜 경로·타입만 로그, `create_engine(hide_parameters=True)` | Starlette 는 Exception 핸들러로 응답한 뒤 예외를 다시 던지고 uvicorn 이 전체 트레이스백(SQL 파라미터의 어르신 말, pydantic input_value)을 남김 → D15 위반 | 로깅 설정으로 uvicorn 에러 로그 끄기 | 디버깅 정보 감소 — 로컬에서 재현해 확인 |
| D33 | 저신뢰(<0.7) 전사 확인은 **화면**이 한다: [맞아요]를 눌러야 `retried=true` 로 보내고, 20초 무조작이면 무응답. 고신뢰는 3초 무조작 확정. 서버의 확인 질문(`confirm_question`)은 다른 클라이언트용으로 남김(들은 말에 금지어가 있으면 되읊지 않음) | 한 번 확인하면 충분. 서버 확인 질문 칩을 그대로 보내면 '맞아요'가 답으로 저장됨 | 3초 뒤 서버 확인 질문 | 서버 잠금(`input_locked`)은 이 화면에선 [다시 말할게요] 2회로 대신함 |
| D34 | 본문 없는 변경 요청은 `api(path, { method: 'POST' })` 로 method 를 꼭 적는다 (`client.ts` 주석) | 기본값이 GET 이라 로그아웃·'다 들었어요'가 405 로 조용히 실패했음(리뷰 11/5) | method 필수 인자 | — |

## 3. 뒤로 미룬 것 (초석 밖)

CI(ci.yml — develop 이 2회 깨지면 tsc 1잡), CODEOWNERS(README 한 줄로 대체), 드리프트 테스트(PR 체크박스), 카카오 로그인(2순위), 브라우저 `SpeechRecognition` 대체 경로, 8초·15초 고정 mp3(`frontend/public/audio/`), 사진 업로드 배치(천주웅), 문제 은행 규칙·되짚기·story_facts(홍진성 11/9 주), 꼬마심심이 연동.
