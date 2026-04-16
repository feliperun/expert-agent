# syntax=docker/dockerfile:1.7
# ------------------------------------------------------------------------------
# Stage 1 — Builder: install deps with uv into /venv
# ------------------------------------------------------------------------------
FROM python:3.12-slim-bookworm AS builder

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PROJECT_ENVIRONMENT=/venv

RUN apt-get update && apt-get install -y --no-install-recommends \
      build-essential \
      ca-certificates \
      curl \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.5 /uv /uvx /usr/local/bin/

WORKDIR /build
COPY pyproject.toml README.md ./
COPY backend/ backend/
COPY cli/ cli/

RUN --mount=type=cache,target=/root/.cache/uv \
    uv venv /venv --python 3.12 && \
    uv sync --frozen --no-dev --extra vertex --extra otel || \
    uv pip install --python /venv/bin/python -e ".[vertex,otel]"

# ------------------------------------------------------------------------------
# Stage 2 — Runtime: slim image with only the venv + app code
# ------------------------------------------------------------------------------
FROM python:3.12-slim-bookworm AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/venv/bin:${PATH}" \
    PORT=8080 \
    APP_ENV=production

RUN apt-get update && apt-get install -y --no-install-recommends \
      ca-certificates \
      tini \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd -r app && useradd -r -g app -d /app -s /sbin/nologin app

COPY --from=builder /venv /venv
WORKDIR /app
COPY --chown=app:app backend/app ./app
COPY --chown=app:app cli/agent_cli ./agent_cli

USER app

EXPOSE 8080

ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080", "--workers", "1", "--loop", "uvloop", "--http", "httptools", "--no-access-log"]
