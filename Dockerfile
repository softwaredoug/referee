FROM python:3.15-slim

COPY --from=ghcr.io/astral-sh/uv:0.8.15 /uv /uvx /bin/

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

WORKDIR /app

COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project

COPY referee ./referee
RUN uv sync --frozen --no-dev

USER 10001:10001
EXPOSE 8080

CMD ["/app/.venv/bin/uvicorn", "referee.api.app:app", "--host", "0.0.0.0", "--port", "8080"]
