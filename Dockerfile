# ── 建置階段 ─────────────────────────────────────────────────────────────────
FROM python:3.11-slim AS builder

WORKDIR /app

# 安裝系統依賴（psycopg2 編譯需要）
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# 先複製依賴清單，讓 Docker layer cache 發揮效益
COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# ── 執行階段 ─────────────────────────────────────────────────────────────────
FROM python:3.11-slim AS runtime

WORKDIR /app

# 執行階段只需要 libpq（psycopg2 runtime）
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    && rm -rf /var/lib/apt/lists/*

# 從 builder 複製已安裝的套件
COPY --from=builder /install /usr/local

# 複製專案程式碼
COPY sentinel/ ./sentinel/
COPY config/ ./config/
COPY alembic/ ./alembic/
COPY alembic.ini .

# 建立非 root 執行使用者
RUN useradd --no-create-home --shell /bin/false app \
    && mkdir -p /app/data /app/outputs \
    && chown -R app:app /app

USER app

# 預設資料目錄（可透過 volume 掛載覆蓋）
VOLUME ["/app/data", "/app/outputs"]

# 健康檢查：驗證套件可載入
HEALTHCHECK --interval=30s --timeout=10s --retries=3 \
    CMD python -c "import sentinel" || exit 1

ENTRYPOINT ["python", "-m", "sentinel"]
CMD ["--help"]
