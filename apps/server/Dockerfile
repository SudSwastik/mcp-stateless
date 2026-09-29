FROM ghcr.io/astral-sh/uv:0.11.3 AS uv
FROM python:3.12-slim

COPY --from=uv /uv /uvx /bin/

RUN groupadd --system app && useradd --system --gid app --home-dir /app app

WORKDIR /app

COPY pyproject.toml uv.lock ./
COPY apps/server/pyproject.toml apps/server/README.md apps/server/
COPY apps/server/src apps/server/src

RUN uv sync --frozen --no-dev --package mcp-stateless-server

ENV PATH="/app/.venv/bin:$PATH"

USER app
EXPOSE 8000

CMD ["uvicorn", "mcp_stateless_server.server:app", "--host", "0.0.0.0", "--port", "8000"]
