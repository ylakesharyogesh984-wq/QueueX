# Production Dockerfile for QueueX on Railway
FROM python:3.11-slim

WORKDIR /app

# Prevent Python from writing .pyc files and enable unbuffered logging
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=5000 \
    FLASK_ENV=production \
    FLASK_DEBUG=0 \
    DATA_DIR=/data

# Install system dependencies (curl for health check, libpq5 for PostgreSQL client, sqlite3)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    libpq5 \
    sqlite3 \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy application source code
COPY . .

# Create volume mount directory for persistent SQLite database
RUN mkdir -p /data

# Expose container port
EXPOSE 5000

# Container healthcheck using Railway /health endpoint
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:${PORT:-5000}/health || exit 1

# Production Gunicorn startup with Socket.IO gthread worker
CMD ["sh", "-c", "gunicorn --worker-class gthread --workers 1 --threads 50 --bind 0.0.0.0:${PORT:-5000} --timeout 120 --keep-alive 5 --access-logfile - --error-logfile - app:app"]
