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

## Web UI（Streamlit Dashboard）

全功能 CLI→UI 儀表板，將所有 CLI 指令映射為可操作頁面，支援長任務背景執行、Command Preview 與 Task Center 追蹤。

### 安裝 UI 依賴

```bash
.venv/bin/python3 -m pip install -e ".[ui]"
```

### 啟動

```bash
# 確保 .env 已設定 TS_DATABASE_URL
.venv/bin/streamlit run ui/app.py
```

瀏覽器自動開啟 `http://localhost:8501`。

### 各頁說明

| 頁面 | 路徑 | 功能 |
|---|---|---|
| Overview | `/`（首頁）| 資料新鮮度、策略命中摘要、最近任務、快速操作 |
| Data Sync | `2_Data_Sync` | init-db / sync-calendar / sync-stocks / sync / backfill-yahoo |
| Daily Scan | `3_Daily_Scan` | run pipeline + scan_results 查詢 + TradingView 匯出 |
| Stock Check | `4_Stock_Check` | check-stock 個股訊號逐條檢核 |
| Backtest | `5_Backtest` | import-minute-bars / backfill-aggregated-bars / backtest |
| Intraday | `6_Intraday` | 盤中快照 / 明日之星掃描 / 模擬交易 / Scheduler |
| Inspect | `7_Inspect` | status / completeness / results / logs / intraday-trades |
| Strategies | `8_Strategies` | strategies.json 啟停管理（先唯讀 + is_active 切換） |
| Task Center | `9_Task_Center` | 全域任務佇列，可查看日誌與重跑任務 |

### 目錄結構

```text
ui/
├── app.py                  # Streamlit 入口（Overview）
├── pages/                  # 各功能頁（Streamlit multipage）
├── components/
│   ├── form_factory.py     # 依 CommandSpec 自動渲染表單
│   ├── command_preview.py  # 指令預覽元件
│   ├── result_table.py     # 高密度結果表格
│   ├── log_viewer.py       # 日誌尾端與任務卡片
│   └── layout.py           # CSS 注入（暗色交易終端主題）
└── services/
    ├── db.py               # @st.cache_resource engine
    ├── command_runner.py   # 任務執行、狀態追蹤
    ├── command_specs.py    # Declarative CLI 規格（新增指令只需此檔）
    ├── queries.py          # 所有 SELECT，回傳 pd.DataFrame
    └── parsers.py          # stdout/stderr 解析器
```

> 規劃文件：[docs/ui-plan.md](docs/ui-plan.md)  
> 規格書：[docs/ui-specification.md](docs/ui-specification.md)

---

## 文件

- [操作手冊](docs/operation-manual.md)
- [實作與操作紀錄](docs/implementation-log.md)
- [UI 規劃存檔](docs/ui-plan.md)
- [專案規格書](project.md)
