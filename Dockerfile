FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    WINGMATES_AUTH=google \
    WINGMATES_DATA_DIR=/data

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY fc ./fc
COPY web ./web
COPY public ./public
COPY data ./data

# One worker process, several threads: SQLite on a local disk cannot have two
# server processes writing. The host sets PORT; 10000 is Render's default.
CMD ["sh", "-c", "exec gunicorn --workers 1 --threads 8 --timeout 60 --bind 0.0.0.0:${PORT:-10000} fc.wsgi:app"]
