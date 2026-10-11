# syntax=docker/dockerfile:1

# --- Build stage: resolve and install locked dependencies into a venv ---
FROM python:3.12-slim AS builder
COPY --from=ghcr.io/astral-sh/uv:0.12.21 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/app/.venv
WORKDIR /app

# Dependencies first, so this layer is cached across source changes.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY src ./src
RUN uv sync --frozen --no-dev --no-editable

# --- Oracle mysqldump: Debian has no mysql-client package and mariadb-client owns
# /usr/bin/mysqldump, so the binary is copied from the official image (needs only
# libssl3/libz/libstdc++, all present in the runtime image). ---
FROM mysql:8.4 AS mysqldump

# --- Runtime stage: venv + migrations + dump tools, non-root ---
FROM python:3.12-slim AS runtime
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    MBP_DATABASE_URL=sqlite:////data/mbp.db \
    MBP_BACKUP_ROOT=/backups

# mariadb-client provides /usr/bin/mariadb-dump for MariaDB servers.
RUN apt-get update \
    && apt-get install -y --no-install-recommends mariadb-client \
    && rm -rf /var/lib/apt/lists/*
COPY --from=mysqldump /usr/bin/mysqldump /usr/local/bin/mysqldump

RUN groupadd --system --gid 10001 mbp \
    && useradd --system --uid 10001 --gid mbp --no-create-home --shell /usr/sbin/nologin mbp \
    && mkdir -p /data /backups \
    && chown mbp:mbp /data /backups

WORKDIR /app
COPY --from=builder /app/.venv /app/.venv
COPY alembic.ini ./
COPY migrations ./migrations

USER mbp
VOLUME ["/data", "/backups"]
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=4)"]

CMD ["sh", "-c", "alembic upgrade head && exec uvicorn mbp.main:app --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips='*'"]
