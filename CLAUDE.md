# CLAUDE.md — AI 코딩 도우미에게 주는 팀 ONLy 규칙

Claude Code 는 이 파일을 자동으로 읽는다. 다른 AI(ChatGPT·Cursor 등)를 쓰면 첫 메시지에 이 파일 전체를 붙여 넣는다.
사람용 안내는 `README.md`, 기술 결정은 `docs/DECISIONS.md`(D번호), 구조는 `docs/ARCHITECTURE.md`.

## 0. 누구를 돕는가

- 서비스: **하루한장** — 가족 사진과 AI 회상 대화로 어르신 정서지원·가족 소통. 어르신 화면(버튼 2개·타이핑 없음)과 가족 화면이 한 PWA.
- 사용자(팀원)는 대부분 **코드 경험이 거의 없다.** 그래서:
  - 한국어로, 쉬운 말로 설명한다. 바꾼 파일과 이유를 짧게 알려 준다.
  - 한 번에 작게 바꾼다. 요청 밖의 파일·리팩터링·"김에 같이" 수정은 하지 않는다.
  - 끝나면 **직접 확인하는 방법**(명령·눌러 볼 화면)을 알려 준다.
  - 모르면 지어내지 말고 "홍진성에게 물어보세요"라고 말한다.

## 1. 절대 하지 않는 것

1. `.env` 를 읽거나 출력하거나 커밋하지 않는다. API 키·비밀번호를 코드·이슈·PR 에 쓰지 않는다(공개 저장소).
2. `main`·`develop` 에 직접 커밋·push 하지 않는다. 작업은 `feature/영역-작업내용` 브랜치에서, 합치기는 PR 로만.
3. `db/schema.sql` 은 **천주웅·홍진성만** 고친다. 다른 사람이 테이블 변경이 필요하면 코드를 고치지 말고 요청 문장을 만들어 준다.
4. 새 라이브러리를 추가하지 않는다(`uv add`, `npm install 이름`). 필요하면 홍진성에게 먼저 묻도록 안내한다. lock 파일은 손으로 고치지 않는다.
5. 실제 사람 이름·전화번호·사진·음성을 코드·시드·테스트에 넣지 않는다.
6. 테스트를 지우거나 `skip` 해서 통과시키지 않는다. 실패하면 원인을 고친다.
7. 다른 사람 담당 폴더(아래 표)는 고치지 않는다. 꼭 필요하면 PR 의 「리뷰어에게」에 이유를 적게 한다.

## 2. 폴더와 담당

- 누가 어느 폴더를 맡는지는 `README.md` **3절 표**가 기준이다. 고치기 전에 그 표에서 사용자 담당인지 확인한다.
- 바뀌지 않는 것: `db/schema.sql` 은 천주웅·홍진성만. `backend/app/ai/`·`frontend/src/components/VoiceSession/` 은 홍진성 담당이고, 이것들과 `schema.sql` 을 고친 PR 은 홍진성이 리뷰한다. API 응답 모양을 바꾼 PR 은 김승희(화면)를 리뷰어로.
- 화면 파일 이름 = 화면설계서 화면 ID (예 `frontend/src/screens/elder/ELDER_HOME_001.tsx`), 경로 표는 `frontend/src/App.tsx` 한 곳.

## 3. 실행·확인 명령

```bash
docker compose up -d db                     # 저장소 루트. DB(내 PC)
cd backend
uv run python -m scripts.seed               # 테이블+시드 다시 넣기 (데이터 지워짐)
uv run uvicorn app.main:app --reload        # 서버 → http://localhost:8000/docs
uv run pytest                               # 서버 테스트 (PR 전 필수)
uv run ruff check . && uv run ruff format --check .
cd ../frontend
npm run dev                                 # 화면 → http://localhost:5173
npm run build && npm run lint               # PR 전 필수
```

PR 을 올리기 전에 위 테스트·빌드가 통과하고 **브라우저에서 직접 눌러 봤는지** 확인하게 한다. 확인 안 한 코드는 PR 에 올리지 않는다.

## 4. 서버 코드 규칙 (Python 3.12 · FastAPI)

- 새 API 는 가까운 기존 파일을 따라 만든다(예: `routers/rooms.py`). 요청·응답 모양은 `app/schemas/` 의 pydantic 모델, 화면 쪽 짝은 `frontend/src/api/types.ts` — 둘을 같이 바꾼다.
- 로그인 확인은 `app/deps.py` 의 `CurrentUser`(가족 쿠키)·`CurrentDevice`(어르신 기기 쿠키)·`require_member(room_id, user, db)` 를 쓴다. 남의 가족방 자료는 있는지도 모르게 404.
- 오류는 `raise ApiError(상태코드, "영문_코드", "어르신·가족이 읽을 한국어 문장")` (`app/errors.py`). 응답은 `{detail, code}`.
- 시간: `datetime.now()` 금지 → `from app.config import now_kst, today_kst`. SQL 에서 `CURRENT_DATE` 금지. 전부 한국 시간(D12, ruff `DTZ` 가 잡음).
- 상한값(턴 수·시간·용량)은 `app/config.py` 상수로(D8). 새 환경 변수는 `Settings` 에 이름을 먼저 추가하고 `settings.이름` 으로 읽는다. `.env.example` 에 빈 칸으로 추가.
- **로그에 어르신·가족이 한 말, 사진 설명, 토큰을 남기지 않는다**(D15). 로그에는 id·개수·시간·예외 타입만.
- 같은 요청이 두 번 와도 한 번만 저장되게 한다(`request_id`, `ON CONFLICT DO NOTHING`). 버튼 두 번 누르기는 실제로 일어난다.
- 서버는 워커 1개 전제(D9) — 메모리에 둔 초안·카운터가 있으니 워커 수를 늘리지 않는다.
- 줄 길이 120, 주석·docstring 은 한국어. 테스트는 `backend/tests/` 에 같은 방식으로 추가(유료 API 는 mock).

## 5. 화면 코드 규칙 (React · TypeScript)

- 서버 호출은 `src/api/client.ts` 의 `api()` 만. 주소는 `/api/...` 상대 주소(Vite 프록시, CORS 없음). 본문 없는 변경 요청도 `{ method: 'POST' }` 를 꼭 적는다(D34).
- 로그인은 쿠키. 토큰을 localStorage·헤더에 넣지 않는다.
- 어르신 화면: 글자 32px 이상(기본 글자 크기 XL 기준. 가족이 '작게(L)'를 고르면 28px — D45), 버튼 88px 이상, 대비 7:1(`src/elder.css` 클래스 사용), 타이핑 입력 없음, 안내는 소리로도.
- 화면 하나 = 파일 하나, 이름은 화면 ID. 아직 없는 화면은 `NotYet` 이 대신한다.

## 6. AI 부품 (홍진성 담당 — 팀원은 읽기만)

- `.env` 가 비어 있으면 전부 **mock**(고정 답·자리표시 그림)으로 돈다. 팀원 PC 에는 키가 필요 없다. 진짜 연결(Claude·Workers AI 그림 D37·STT·TTS)은 홍진성 PC 와 배포 서버에서만.
- 어르신 말은 프롬프트에 JSON **데이터**로만 넣고, 모델 출력은 코드가 다시 검사한다(금지어 `data/banned_words.json`, 질문 1개, 길이). 프롬프트는 `backend/app/ai/prompts/*.md`.

## 7. 이름·커밋·PR

- 브랜치 `feature/fe-…`·`feature/be-…`·`feature/db-…`·`feature/ai-…`·`fix/…`·`docs/…` (영어 소문자, `-`). 일정표 작업 번호의 브랜치 이름을 그대로 쓴다.
- 커밋 `종류(영역): 무엇을 했는지` — 예 `feat(be): 사진 업로드 API`. 종류 feat·fix·docs·refactor·chore.
- PR 은 `.github/pull_request_template.md` 칸을 채운다. 이슈가 있으면 `Closes #번호`. 「리뷰어에게」에 **AI 가 만든 코드 중 이해 못 한 부분**을 적는다.
- PR 을 올리면 **그 브랜치에는 더 커밋하지 않는다**(리뷰 지적도 같은 브랜치에서 고치지 않는다). 합치기·다듬기는 저녁에 홍진성이 한다. 다음 작업은 `develop` 최신본에서 새 브랜치로 시작하게 안내한다.
- 기술 결정을 바꾸면 `docs/DECISIONS.md` 에 D번호로 한 줄(이유·대안·트레이드오프).
