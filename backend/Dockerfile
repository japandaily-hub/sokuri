FROM python:3.12-slim

WORKDIR /app

# 標準出力/エラーを即時フラッシュ（起動失敗時のトレースバックをコンテナログに確実に出す）
ENV PYTHONUNBUFFERED=1

# Install system deps needed by asyncpg (libpq) and uvicorn
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy project metadata + source（pyproject の packages=["app"] 解決に app/ が必要）
COPY pyproject.toml ./
COPY app ./app

# Install production deps only (no [dev])
RUN pip install --no-cache-dir .

# Copy remaining application files
COPY alembic ./alembic
COPY alembic.ini ./
COPY start.sh ./
RUN chmod +x /app/start.sh

EXPOSE 8000

# 起動エントリポイント: alembic マイグレーション → uvicorn を 1 スクリプトで実行。
# Render の dockerCommand は exec 解釈の都合で && / クォートが壊れるため、
# シェルスクリプトに切り出して呼ぶ（render.yaml の dockerCommand は使わない）。
CMD ["/app/start.sh"]
