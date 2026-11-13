"""설정 1곳. .env(저장소 루트)를 읽고, 값이 없으면 개발용 기본값으로 mock 실행이 되게 한다.

시간대는 여기서만 정한다(설계 결정 D12): TZ, now_kst(), today_kst() 외에 datetime.now()를 직접 쓰지 않는다.
"""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]  # only-app/
TZ = ZoneInfo("Asia/Seoul")

# 개발 기본값. 배포(APP_ENV=deploy)에서 이 값 그대로면 기동 거부 (D20 + "값 없이 실행" 절충)
DEV_JWT_SECRET = "dev-only-jwt-secret-change-me-before-deploy-0000"

# 상한값은 설정 테이블 대신 상수 (D8)
MAX_TURNS = 6  # 회상 AI 질문 수: 회상 3 → 문제 1 → 회상 2 (D52 ⑦, 11/12 전 8). DB CHECK 0~8 은 그대로
DIARY_TURNS = 3  # 일기 대화 질문 수: 뭐 하셨어요 → 누구랑 → 기분은 (FR-DI-003)
DIARY_DRAFT_MIN = 30  # 일기 초안 유지 시간 (FR-DI-004)
QUIZ_TURN = 4  # 회상 3턴(어떠세요 → 누구랑 → 그때 이야기) 뒤 4번째 AI 질문이 문제 은행 문제 (FR-AI-001·002, D42)
QUIZ_PER_DAY = 2  # 가족방 하루 문제 상한 (FR-AI-002 '하루 1~2문제'). 세션당은 1개
QUIZ_REPEAT_DAYS = 14  # 최근 14일에 쓴 활동·주제·문제는 빼고 고른다 (D39)
PHOTO_CONF_MIN = 0.7  # 사진 분류 신뢰도가 이 미만이면 none 사진으로 본다 (FR-ME-003)
MAX_SESSION_SEC = 300  # 5분 (대화한 시간)
PAUSE_GAP_SEC = 90  # 턴 사이가 이보다 길면 보류로 보고 90초만 센다 (무응답 3단계 60초 + 여유)
ALBUM_PER_DAY = 3
ALBUM_TURNS = 2  # 사진첩 대화 장당 AI 질문 수 (FR-ME-008)
# 가족 사진 목록·어르신 사진첩이 한 번에 돌려주는 장수(최신 순) — 두 화면이 같은 사진을 보이게 한 값으로 (D8)
PHOTO_LIST_LIMIT = 100
NOTI_LIST_LIMIT = 50  # 가족 알림 목록이 한 번에 돌려주는 개수, 최신 순
ELDER_PUSH_PER_DAY = 2
SESSION_RESUME_MIN = 30  # 마지막 턴 후 30분 지나면 ENDED 취급
STT_CONF_MIN = 0.7  # 이 미만이면 확인 질문
STT_FAIL_LOCK = 2  # 세션 안 저신뢰 2회 → input_locked
NO_RESPONSE_END = 3  # 무응답 3단계째 종료
SESSION_ERROR_ALERT = 3  # 하루 ERROR 종료 3회 → 가족 알림
PICK_SKIP_ALERT = 2  # 같은 사진 건너뛰기 2회 → 가족 알림 (FR-ME-005)
NO_RECORD_DAYS = 2  # 이 날수만큼 어르신 기록이 없으면 가족 알림 (FR-NT-003)
WEEKLY_HOUR = 19  # 주간 집계는 일요일 이 시각, D19 — 집계 창과 예약 시각이 같이 쓴다
MOOD_LOW_DAYS = 2  # 기운 없는 말이 나온 날이 최근 MOOD_LOW_WINDOW_DAYS 일 중 이만큼이면 가족 알림 1건 (D55 ②)
MOOD_LOW_WINDOW_DAYS = 7  # 위 날수를 세는 기간이자, 같은 알림을 다시 보내지 않는 기간
# 일기 사진이 옛 사진이면(분류 is_old + 신뢰도 이 이상) 일기 1·2번 질문을 그 사진 속 그때로 (FR-DI-002, D58)
OLD_PHOTO_CONF_MIN = 0.8
FAMILY_TEXT_MAX = 200  # 가족 일기 한마디·답 글자 수 (FR-DI-006)
FAMILY_AI_RATE_PER_MIN = 10  # 가족 일기 동무(질문·초안) 같은 사람 분당 상한. 한 사람이 하루 상한을 다 쓰지 못하게 (D58)
STT_MAX_BYTES = 5 * 1024 * 1024
STT_MAX_SEC = 60  # 녹음 상한 (FR-VS-001, 화면 RECORD_MS). 더 긴 소리는 변환할 때 잘라 STT 과금·메모리를 막는다
# 전사 상한. 턴 본문 상한(schemas/sessions.py TurnIn.text)과 같게 — 넘으면 턴이 422 로 대화를 끝낸다
STT_MAX_CHARS = 500
UPLOAD_MAX_BYTES = 10 * 1024 * 1024
UPLOAD_MAX_FILES = 20  # 한 번에 올리는 사진 수 (D17)
UPLOAD_MAX_PIXELS = 30_000_000  # 사진 한 장 픽셀 수(가로×세로). 넘으면 거절 — 서버 메모리 보호 (D17)
UPLOAD_MAX_SIDE = 65_500  # 사진 한 변 픽셀. 길쭉한 조작 그림(1×3천만)은 줄 주소표만 240MB — JPEG 한계와 같게 (D17)
UPLOAD_MAX_EXIF_BYTES = 64 * 1024  # 사진 정보(EXIF). 폰 사진은 64KB 안 — 넘으면 회전·촬영일을 읽지 않음 (D17)
UPLOAD_MAX_ICC_BYTES = 64 * 1024  # 색 프로필(ICC). 넘거나 RGB 프로필이 아니면 프로필 없이 저장 (D17)
UPLOAD_MAX_EXIF_SEGMENTS = 4  # 파일 속 EXIF 조각 수. 보통 1개, 여러 장 묶음도 2~3개 — 넘으면 거절 (D17)
JPEG_MAX_SCANS = 300  # JPEG 스캔(FF DA) 수. 보통 1~10개, 움직이는 사진 뒤 영상에서 우연히 나오는 것까지 넉넉히 (D17)
PHOTO_MAX_SIDE = 2560  # 저장 사진 긴 변(px). 넘으면 비율 그대로 줄여 저장 (D17)
UPLOAD_LOCK_WAIT_SEC = 60  # 사진 변환은 서버 전체에서 한 번에 한 요청. 이만큼 기다려도 차례가 안 오면 503 (D17)
LOGIN_RATE_PER_MIN = 10
STT_RATE_PER_MIN = 20  # 같은 IP 의 /api/stt 분당 상한. 대화 한 번(5분)에 많아야 16번 부른다 (D46)
# 서버 전체 하루 상한 — 돈이 드는 호출(rtzr·google·anthropic)만 세고 한국 자정에 0 (D46 ⑨). 가입은 누구나 된다.
# 회상 대화 1번 ≈ Claude 9·TTS 10·STT 최대 16번. 300 이면 하루 대화 20~30번 — 11/27 검증판 배포 때 다시 정함
STT_PER_DAY = 300  # 리턴제로. 넘으면 429 → 화면이 그 문장을 읽고 버튼으로
TTS_PER_DAY = 300  # Google. 넘으면 브라우저 목소리 (D5, 가족 알림 없음)
LLM_PER_DAY = 300  # Claude call_json 1번(검증 재시도 포함 최대 2요청). 넘으면 고정 문장 (D14)
SESSION_COOKIE_DAYS = 7
DEVICE_COOKIE_DAYS = 365
MOOD_WEEK_DAYS = 7  # 가족 홈 마음 카드가 보여 주는 날수


class Settings(BaseSettings):
    # env_ignore_empty: .env 에 "KEY=" 처럼 비워 둔 값은 기본값으로 (값 없이 mock 실행)
    model_config = SettingsConfigDict(env_file=ROOT / ".env", extra="ignore", env_ignore_empty=True)

    APP_ENV: str = "dev"  # dev | deploy
    DATABASE_URL: str = "postgresql+psycopg://only:only@127.0.0.1:5432/only_app"
    JWT_SECRET: str = DEV_JWT_SECRET
    SCHEDULER_ENABLED: bool = True

    ANTHROPIC_API_KEY: str = ""
    LLM_PROVIDER: str = "mock"  # mock | anthropic
    LLM_MODEL: str = "claude-haiku-5-5"
    STT_PROVIDER: str = "mock"  # mock | rtzr | ...
    TTS_PROVIDER: str = "mock"  # mock | google | ...
    IMAGE_PROVIDER: str = "mock"  # mock | cloudflare

    STORAGE: str = "local"  # local | r2
    UPLOAD_DIR: str = str(ROOT / "uploads")
    DOMAIN: str = ""

    # 이름만 예약 (키를 받으면 .env 에 채움)
    R2_ACCOUNT_ID: str = ""
    R2_ACCESS_KEY_ID: str = ""
    R2_SECRET_ACCESS_KEY: str = ""
    R2_BUCKET: str = ""
    RTZR_CLIENT_ID: str = ""
    RTZR_CLIENT_SECRET: str = ""
    GOOGLE_TTS_API_KEY: str = ""
    CF_ACCOUNT_ID: str = ""
    CF_API_TOKEN: str = ""

    @property
    def is_dev(self) -> bool:
        return self.APP_ENV == "dev"


settings = Settings()

if len(settings.JWT_SECRET) < 32:
    raise RuntimeError("JWT_SECRET 은 32자 이상이어야 합니다 (.env)")
if not settings.is_dev and settings.JWT_SECRET == DEV_JWT_SECRET:
    raise RuntimeError("배포 환경(APP_ENV=deploy)에서는 JWT_SECRET 을 개발 기본값으로 둘 수 없습니다")


def now_kst() -> datetime:
    return datetime.now(TZ)


def today_kst() -> date:
    return now_kst().date()
