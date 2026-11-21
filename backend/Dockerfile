FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN useradd --create-home --uid 1000 appuser

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY --chown=appuser:appuser . .

RUN mkdir -p /app/uploads /app/assets/seed && chown -R appuser:appuser /app

USER appuser

ENV CIVIC_HOST=0.0.0.0 \
    CIVIC_PORT=7860 \
    CIVIC_ENVIRONMENT=demo \
    CIVIC_LOG_JSON=true \
    CIVIC_UPLOAD_DIR=/app/uploads \
    CIVIC_DATABASE_URL=sqlite+aiosqlite:///./civicresolve.db \
    CIVIC_SEED_ON_STARTUP=true \
    CIVIC_DEMO_RESET_ENABLED=true \
    CIVIC_USE_DEMO_SLA=true

EXPOSE 7860

HEALTHCHECK --interval=30s --timeout=5s --start-period=25s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:7860/healthz')"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "7860"]