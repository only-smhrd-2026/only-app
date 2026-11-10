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
MAX_TURNS = 8  # 세션당 AI 질문 수 (sessions.turn_count CHECK 0~8)
DIARY_TURNS = 3  # 일기 대화 질문 수: 뭐 하셨어요 → 누구랑 → 기분은 (FR-DI-003)
DIARY_DRAFT_MIN = 30  # 일기 초안 유지 시간 (FR-DI-004)
QUIZ_TURN = 4  # 회상 3턴(어떠세요 → 누구랑 → 그때 이야기) 뒤 4번째 AI 질문이 문제 은행 문제 (FR-AI-001·002, D42)
QUIZ_PER_DAY = 2  # 가족방 하루 문제 상한 (FR-AI-002 '하루 1~2문제'). 세션당은 1개
QUIZ_REPEAT_DAYS = 14  # 최근 14일에 쓴 활동·주제·문제는 빼고 고른다 (D39)
PHOTO_CONF_MIN = 0.7  # 사진 분류 신뢰도가 이 미만이면 none 사진으로 본다 (FR-ME-003)
MAX_SESSION_SEC = 300  # 5분 (대화한 시간)
PAUSE_GAP_SEC = 90  # 턴 사이가 이보다 길면 보류로 보고 90초만 센다 (무응답 3단계 60초 + 여유)
ALBUM_PER_DAY = 3
ELDER_PUSH_PER_DAY = 2
SESSION_RESUME_MIN = 30  # 마지막 턴 후 30분 지나면 ENDED 취급
STT_CONF_MIN = 0.7  # 이 미만이면 확인 질문
STT_FAIL_LOCK = 2  # 세션 안 저신뢰 2회 → input_locked
NO_RESPONSE_END = 3  # 무응답 3단계째 종료
SESSION_ERROR_ALERT = 3  # 하루 ERROR 종료 3회 → 가족 알림
STT_MAX_BYTES = 5 * 1024 * 1024
STT_MAX_SEC = 60  # 녹음 상한 (FR-VS-001, 화면 RECORD_MS). 더 긴 소리는 변환할 때 잘라 STT 과금·메모리를 막는다
# 전사 상한. 턴 본문 상한(schemas/sessions.py TurnIn.text)과 같게 — 넘으면 턴이 422 로 대화를 끝낸다
STT_MAX_CHARS = 500
UPLOAD_MAX_BYTES = 10 * 1024 * 1024
LOGIN_RATE_PER_MIN = 10
STT_RATE_PER_MIN = 20  # 같은 IP 의 /api/stt 분당 상한. 대화 한 번(5분)에 많아야 16번 부른다 (D46)
SESSION_COOKIE_DAYS = 7
DEVICE_COOKIE_DAYS = 365


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
