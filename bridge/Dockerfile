# AI NVR bridge — Python 3.13 multistage
# Builder: uv ile bağımlılık install
# Runtime: minimal image, non-root user, healthcheck

FROM python:3.13-slim AS builder

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app
ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PYTHON_DOWNLOADS=never

# Milestone-bazlı opsiyonel grup install (M2.5 dependency-groups split).
# Build arg ile aktive: docker compose'da `args:` ile veya
# `docker build --build-arg INSTALL_LLM=true ...`
# Default false → sadece core deps install (M1-M2 için yeterli).
ARG INSTALL_LLM=false
ARG INSTALL_VIEWER=false

# pyproject + uv.lock kopyala, `--frozen` ile reproducible install.
# --no-install-project zorunlu: bridge/ kaynak henüz kopyalanmadı,
# hatchling.build'ı tetiklememek için. Fallback (|| uv sync --no-dev)
# eklenmemeli — gerçek hataları gizler.
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    sh -c 'GROUPS=""; \
           [ "$INSTALL_LLM" = "true" ] && GROUPS="$GROUPS --group llm"; \
           [ "$INSTALL_VIEWER" = "true" ] && GROUPS="$GROUPS --group viewer"; \
           uv sync --frozen --no-install-project --no-dev $GROUPS'

COPY bridge ./bridge
COPY alembic.ini ./
COPY alembic ./alembic
RUN --mount=type=cache,target=/root/.cache/uv \
    sh -c 'GROUPS=""; \
           [ "$INSTALL_LLM" = "true" ] && GROUPS="$GROUPS --group llm"; \
           [ "$INSTALL_VIEWER" = "true" ] && GROUPS="$GROUPS --group viewer"; \
           uv sync --frozen --no-dev $GROUPS'


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
