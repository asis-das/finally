# syntax=docker/dockerfile:1
#
# FinAlly — AI Trading Workstation
# Multi-stage: Node builds the Next.js static export, Python serves it plus the API.

# ---------------------------------------------------------------------------
# Stage 1 — build the Next.js static export
# ---------------------------------------------------------------------------
FROM node:22-slim AS frontend

# Corporate CA support. docker/ca/ always exists (it holds a README), so this
# COPY never fails; any *.crt in it is added to the trust store. next/font
# downloads Google Fonts at build time, so a TLS-intercepting proxy breaks the
# build without this. Verification stays ON.
COPY docker/ca/ /usr/local/share/ca-certificates/finally/
RUN set -eux; \
    if ls /usr/local/share/ca-certificates/finally/*.crt >/dev/null 2>&1; then \
        apt-get update && apt-get install -y --no-install-recommends ca-certificates; \
        update-ca-certificates; \
        rm -rf /var/lib/apt/lists/*; \
    fi
ENV NODE_EXTRA_CA_CERTS=/etc/ssl/certs/ca-certificates.crt

WORKDIR /build

# Dependency manifests first so the install layer caches independently of source.
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

COPY frontend/ ./
RUN npm run build

# Fail loudly here rather than shipping an image that 404s on /.
RUN test -f out/index.html || (echo "ERROR: static export missing out/index.html" >&2; exit 1)

# ---------------------------------------------------------------------------
# Stage 2 — Python runtime
# ---------------------------------------------------------------------------
FROM python:3.12-slim AS runtime

COPY docker/ca/ /usr/local/share/ca-certificates/finally/
RUN set -eux; \
    apt-get update; \
    apt-get install -y --no-install-recommends ca-certificates curl; \
    update-ca-certificates; \
    rm -rf /var/lib/apt/lists/*
# LiteLLM/httpx/requests read these; keeps OpenRouter reachable behind a proxy.
ENV SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt \
    REQUESTS_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/app/backend/.venv \
    PATH="/app/backend/.venv/bin:$PATH"

WORKDIR /app/backend

# Lockfile-only install first, so source edits don't invalidate the dependency layer.
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --no-install-project --no-dev

COPY backend/ ./
RUN uv sync --frozen --no-dev

# config.PROJECT_ROOT is parents[2] of app/config.py -> /app, so a relative
# FINALLY_DB_PATH would land in /app/db anyway; absolute is explicit.
COPY --from=frontend /build/out /app/static
ENV FINALLY_DB_PATH=/app/db/finally.db \
    FINALLY_STATIC_DIR=/app/static

# /app/db is the volume mount point and must be writable by the runtime user.
RUN useradd --create-home --uid 10001 finally \
    && mkdir -p /app/db \
    && chown -R finally:finally /app
USER finally

EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8000/api/health || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
