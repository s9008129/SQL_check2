# syntax=docker/dockerfile:1
#
# Single-container build (PRD §5, §48): Node is only ever used in the build
# stage; the runtime image has no Node, no Ollama, no database — just the
# FastAPI app serving its own built React static files, per PRD §5's
# explicit "not included" list.

# ---- Stage 1: frontend build ----
FROM node:22-alpine AS frontend-build
WORKDIR /src/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# ---- Stage 2: Python runtime ----
FROM python:3.12-slim AS runtime

COPY --from=ghcr.io/astral-sh/uv:0.12.5 /uv /usr/local/bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONIOENCODING=utf-8 \
    PYTHONUTF8=1

WORKDIR /app/backend

# Dependencies first for better layer caching; app code changes far more
# often than pyproject.toml/uv.lock.
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY backend/app ./app
RUN uv sync --frozen --no-dev

COPY --from=frontend-build /src/frontend/dist ./static

RUN useradd --create-home --uid 10001 sqlcheck \
    && mkdir -p /certs /data/sql_archive \
    && chown -R sqlcheck:sqlcheck /app /certs /data
USER sqlcheck

ENV PATH="/app/backend/.venv/bin:${PATH}"

# The app always listens on a single internal port (8000), HTTPS when
# /certs holds a certificate+key, plain HTTP otherwise (app/run.py). The
# external port (443 in production) is chosen by docker-compose.yml, not
# here — keeps the image itself deploy-target-agnostic.
EXPOSE 8000

# Verification is not disabled: when a cert exists, the healthcheck pins to
# that exact self-signed certificate as its trust anchor (ssl.create_default_
# context(cafile=...)) instead of turning verification off — equivalent to
# certificate pinning, not a MITM-enabling bypass. This requires
# app/certgen.py's SAN list to include 127.0.0.1 (loopback), which it does.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "\
import os, ssl, urllib.request; \
cert = '/certs/sqlcheck.crt'; \
has_tls = os.path.exists(cert); \
ctx = ssl.create_default_context(cafile=cert) if has_tls else None; \
scheme = 'https' if has_tls else 'http'; \
urllib.request.urlopen(f'{scheme}://127.0.0.1:8000/api/health', timeout=3, context=ctx)" \
    || exit 1

CMD ["python", "-m", "app.run"]
