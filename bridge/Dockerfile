# AI NVR bridge — Python 3.13 multistage
# Builder: uv ile bağımlılık install
# Runtime: minimal image, non-root user, healthcheck

FROM python:3.13-slim AS builder

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app
ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PYTHON_DOWNLOADS=never

COPY pyproject.toml ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --no-install-project --no-dev || uv sync --no-dev

COPY bridge ./bridge
COPY alembic.ini ./
COPY alembic ./alembic
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --no-dev


FROM python:3.13-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

RUN groupadd -r ainvr && useradd -r -g ainvr ainvr \
    && mkdir -p /var/lib/ainvr && chown ainvr:ainvr /var/lib/ainvr

COPY --from=builder --chown=ainvr:ainvr /app /app

USER ainvr

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import bridge" || exit 1

CMD ["python", "-m", "bridge.main"]
