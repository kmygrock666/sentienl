# Trading System MVP

跨市場策略選股系統，聚焦台股（TWSE / TPEX）日線資料抓取、技術指標計算、規則式策略掃描與回測。

## 專案結構

```text
sentinel/
├── .github/
│   └── workflows/
│       └── ci.yml              # GitHub Actions CI
├── alembic/                    # DB 遷移腳本
│   └── versions/
├── config/
│   └── strategies.json         # 策略設定檔
├── docs/
│   ├── operation-manual.md     # 操作手冊
│   └── implementation-log.md   # 實作紀錄
├── scripts/                    # 輔助腳本（不進生產）
├── tests/                      # pytest 測試套件
│   └── fixtures/               # 離線測試 fixture
├── sentinel/             # 主套件
│   ├── intraday/               # 日內策略模組
│   ├── cli.py                  # CLI 入口
│   ├── pipeline.py             # 抓取→計算→掃描→輸出
│   ├── providers.py            # TWSE / TPEx provider
│   ├── indicators.py           # 技術指標引擎
│   ├── strategies.py           # 策略掃描邏輯
│   ├── backtest.py             # 回測引擎
│   ├── models.py               # SQLAlchemy ORM
│   ├── db.py                   # DB engine / schema 初始化
│   ├── persistence.py          # DB 寫入邏輯
│   ├── config.py               # pydantic-settings（TS_ prefix）
│   └── ...
├── .env.example
├── .pre-commit-config.yaml
├── docker-compose.yml
├── Dockerfile
├── Makefile
├── pyproject.toml
└── requirements.txt
```

## 快速開始

### 1. 建立虛擬環境

```bash
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
```

### 2. 安裝依賴

```bash
# 生產依賴
pip install -r requirements.txt

# 開發依賴（含 linting / 測試）
pip install -r requirements-dev.txt

# 或透過 Makefile
make install-dev
```

### 3. 設定環境變數

```bash
cp .env.example .env
# 視需求修改 .env
```

### 4. 執行測試

```bash
make test
# 或帶覆蓋率
make test-cov
```

### 5. 初始化資料庫

```bash
make init-db
```

### 6. 日線資料抓取與掃描

```bash
python -m sentinel run \
  --market TWSE \
  --market TPEX \
  --strategy-path config/strategies.json \
  --database-url sqlite:///data/db/sentinel.db \
  --start-date 2026-01-01 \
  --end-date 2026-03-06
```

### 7. 回測

```bash
python -m sentinel backtest \
  --start-date 2026-01-01 \
  --end-date 2026-03-06 \
  --market TWSE \
  --market TPEX \
  --strategy-path config/strategies.json \
  --database-url sqlite:///data/db/sentinel.db
```

---

## 使用 Docker

```bash
# 啟動 PostgreSQL + TimescaleDB
make docker-up

# 執行指令
docker compose run --rm app run --market TWSE --start-date 2026-01-01 --end-date 2026-03-06

# 停止
make docker-down
```

---

## 開發工作流程

```bash
make format      # black + isort 格式化
make lint        # ruff linting
make type-check  # mypy 型別檢查
make check       # 以上三者一次執行
make test        # pytest
make test-cov    # pytest + 覆蓋率報告
```

---

## 資料庫遷移

```bash
# SQLite（開發）
make init-db

# PostgreSQL（正式）
TS_DATABASE_URL=postgresql+psycopg2://postgres:postgres@localhost:5432/sentinel \
  make migrate
```

---

## 輸出結構

```text
data/processed/
  daily_prices.csv        # 日線資料集
  stocks.csv              # 股票主檔

outputs/
  YYYY-MM-DD/
    scan_results.csv
    scan_results.json
    scan_results.md
    tradingview_YYYY-MM-DD.txt
  backtests/
    YYYY-MM-DD_YYYY-MM-DD/
      report.csv
      trades.csv
```

---

## 技術棧

| 項目 | 選用 |
|------|------|
| 語言 | Python 3.9+ |
| 資料庫（開發） | SQLite |
| 資料庫（正式） | PostgreSQL 16 + TimescaleDB |
| ORM | SQLAlchemy 2.x |
| 遷移 | Alembic |
| 設定 | pydantic-settings（`TS_` prefix） |
| 測試 | pytest |
| Linting | ruff + black + isort |
| 型別檢查 | mypy |
| 排程 | APScheduler |
| 容器 | Docker + docker-compose |
| CI | GitHub Actions |

---

## 文件

- [操作手冊](docs/operation-manual.md)
- [實作與操作紀錄](docs/implementation-log.md)
- [專案規格書](project.md)
