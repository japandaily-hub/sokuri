FROM python:3.12-slim

WORKDIR /app

# Install system deps needed by asyncpg (libpq) and uvicorn
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy project metadata first for layer caching
COPY pyproject.toml ./

# Install production deps only (no [dev])
RUN pip install --no-cache-dir .

# Copy application source
COPY app ./app
COPY alembic ./alembic
COPY alembic.ini ./

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
