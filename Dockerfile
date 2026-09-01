FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app

COPY . /app
RUN python -m pip install --no-cache-dir ".[api]" \
    && python -c "import importlib.util; assert all(importlib.util.find_spec(name) is None for name in ('docx', 'openpyxl', 'pdfplumber'))" \
    && adduser --disabled-password --gecos "" --uid 10001 cfr

USER cfr
EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=3s --start-period=10s --retries=5 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=2)"

CMD ["cfr", "serve", "--host", "0.0.0.0", "--port", "8000"]
