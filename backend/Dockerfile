# 배포용 API 이미지. 빌드 컨텍스트는 저장소 루트 (db/, data/ 도 필요). docker-compose.yml 의 api 서비스가 사용.
FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PROJECT_ENVIRONMENT=/opt/venv TZ=Asia/Seoul
WORKDIR /app/backend

COPY backend/pyproject.toml backend/uv.lock backend/.python-version ./
RUN uv sync --frozen --no-dev

COPY backend/ ./
COPY db/ /app/db/
COPY data/ /app/data/

ENV PATH="/opt/venv/bin:$PATH"
EXPOSE 8000
# --workers 1: APScheduler 가 두 번 돌지 않게 (D9). --proxy-headers: Caddy 뒤에서 https/클라이언트 IP 인식 (D7)
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--proxy-headers", "--forwarded-allow-ips=*"]
