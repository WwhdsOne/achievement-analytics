# Python 只存在于独立推荐容器；dashboard 仍为纯 Go / scratch。
FROM ghcr.io/astral-sh/uv:0.13.1-python3.13-trixie-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 UV_LINK_MODE=copy
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project --no-cache
COPY result/ZZY/ ./result/ZZY/
COPY health.py ./health.py
ENTRYPOINT ["/app/.venv/bin/python", "-u", "/app/result/ZZY/dashboard_service.py"]
