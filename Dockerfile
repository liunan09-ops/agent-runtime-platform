FROM python:3.11-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    DATABASE_URL=sqlite+aiosqlite:////app/runtime-data/runtime.db
WORKDIR /app
COPY requirements.lock pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir -r requirements.lock && pip install --no-cache-dir --no-deps . \
    && useradd --uid 10001 --create-home runtime \
    && mkdir -p /app/runtime-data && chown runtime:runtime /app/runtime-data
USER runtime
EXPOSE 8000
HEALTHCHECK --interval=5s --timeout=3s --start-period=5s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=2)"
CMD ["uvicorn", "agent_runtime.api:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]

