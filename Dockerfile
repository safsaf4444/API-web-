FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD alembic upgrade head && \
    uvicorn backend.app:app \
    --host 0.0.0.0 \
    --port ${PORT:-8000} \
    --workers 2 \
    --no-access-log