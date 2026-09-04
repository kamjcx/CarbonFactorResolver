# syntax=docker/dockerfile:1.7

FROM ghcr.io/astral-sh/uv:0.11.7@sha256:240fb85ab0f263ef12f492d8476aa3a2e4e1e333f7d67fbdd923d00a506a516a AS uv-bin

FROM python:3.11.16-slim-trixie@sha256:9534e5a8e315485d4061ed659af0fd78a284c015f9b73661b41d6bab25604534 AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy
WORKDIR /app

COPY --from=uv-bin /uv /usr/local/bin/uv
COPY pyproject.toml uv.lock LICENSE ./
# Install the runtime equivalent of ".[api]" exclusively from the frozen uv lock.
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --extra api --no-install-project

COPY src/ ./src/
COPY data/benchmarks/*.jsonl ./data/benchmarks/
COPY data/fixtures/catalog/ ./data/fixtures/catalog/
COPY data/fixtures/external/ ./data/fixtures/external/
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --extra api --no-editable \
    && python -c "import importlib.util; assert all(importlib.util.find_spec(name) is None for name in ('docx', 'openpyxl', 'pdfplumber'))"

FROM python:3.11.16-slim-trixie@sha256:9534e5a8e315485d4061ed659af0fd78a284c015f9b73661b41d6bab25604534

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH"
WORKDIR /app

COPY --from=builder /app/.venv /app/.venv
RUN adduser --disabled-password --gecos "" --uid 10001 cfr

USER cfr
EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=3s --start-period=10s --retries=5 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=2)"

CMD ["cfr", "serve", "--host", "0.0.0.0", "--port", "8000"]
