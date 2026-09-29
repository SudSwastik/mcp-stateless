FROM ghcr.io/astral-sh/uv:0.11.3 AS uv
FROM python:3.12-slim

COPY --from=uv /uv /uvx /bin/

RUN groupadd --system app && useradd --system --gid app --home-dir /app app

WORKDIR /app

COPY pyproject.toml uv.lock ./
COPY apps/client/pyproject.toml apps/client/README.md apps/client/
COPY apps/server/pyproject.toml apps/server/README.md apps/server/
COPY apps/client/src apps/client/src

RUN uv sync --frozen --no-dev --package mcp-stateless-client

ENV PATH="/app/.venv/bin:$PATH"

USER app

ENTRYPOINT ["mcp-stateless-client"]
CMD ["verify"]
