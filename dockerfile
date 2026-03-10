FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install system deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Copy and install Python deps first (layer cache)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Run Alembic migrations then start server
CMD alembic upgrade head && \
    uvicorn backend.app:app \
    --host 0.0.0.0 \
    --port ${PORT:-8000} \
    --workers 2 \
    --no-access-log