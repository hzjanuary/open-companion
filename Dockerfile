FROM ghcr.io/astral-sh/uv:0.6.5 AS uv

FROM python:3.12-slim AS builder

COPY --from=uv /uv /uvx /bin/
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy

COPY pyproject.toml uv.lock alembic.ini LICENSE NOTICE ./
RUN uv sync --locked --no-dev --no-install-project

COPY backend ./backend
COPY alembic ./alembic
RUN uv sync --locked --no-dev

FROM python:3.12-slim AS runtime

RUN groupadd --system january && useradd --system --gid january --create-home january
WORKDIR /app
ENV PATH="/app/.venv/bin:$PATH" PYTHONPATH="/app/backend" PYTHONUNBUFFERED=1

COPY --from=builder --chown=january:january /app/.venv /app/.venv
COPY --chown=january:january LICENSE NOTICE ./
COPY --chown=january:january backend ./backend
COPY --chown=january:january alembic.ini ./
COPY --chown=january:january alembic ./alembic
COPY --chown=january:january scripts/self_host ./self-host

USER january
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
