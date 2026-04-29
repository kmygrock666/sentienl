# AGENTS.md

## 語言偏好

所有回覆、註解、commit message 請使用**繁體中文**。程式碼中的變數名稱、函式名稱維持**英文**。

## 專案概述

跨市場策略選股系統，聚焦台股 (TWSE/TPEX) 日線資料抓取、技術指標計算、規則式策略掃描、回測、以及日內（隔日沖）策略模組。

## 技術棧

| 項目 | 選用 |
|------|------|
| 語言 | Python 3.9+ (開發環境為 3.9) |
| 虛擬環境 | `.venv/`（必須在此環境內執行） |
| 依賴管理 | `pip` + `requirements.txt` / `requirements-dev.txt` |
| 專案設定 | `pyproject.toml`（black / ruff / mypy / pytest 設定集中在此） |
| 資料庫 | SQLite (開發) / PostgreSQL 16 + TimescaleDB (正式) |
| ORM | SQLAlchemy 2.x |
| 遷移 | Alembic |
| 設定管理 | `.env` + `pydantic-settings`，env prefix 為 `TS_` |
| 測試框架 | `pytest` / `unittest` |
| 程式碼格式 | `black` + `isort` |
| Linting | `ruff` |
| 型別檢查 | `mypy` |
| Pre-commit | `.pre-commit-config.yaml`（black / isort / ruff） |
| 排程 | APScheduler (`sentinel/intraday/scheduler.py`) |
| 日誌 | 結構化 JSON 日誌 (`sentinel/logging_utils.py`) |
| 容器 | Docker + docker-compose（PostgreSQL + TimescaleDB） |
| CI | GitHub Actions (`.github/workflows/ci.yml`) |

## 專案結構

```
sentinel/             # 主套件
├── cli.py                  # CLI 入口（所有指令）
├── pipeline.py             # 日線：抓取、計算、掃描、輸出流程
├── providers.py            # TWSE / TPEX 日線資料 provider
├── indicators.py           # 技術指標計算引擎
├── strategies.py           # 策略定義與掃描邏輯
├── backtest.py             # 回測引擎
├── storage.py              # 檔案型資料集 upsert
├── config.py               # pydantic-settings 設定類
├── db.py                   # DB engine / schema 初始化
├── models.py               # SQLAlchemy ORM models
├── persistence.py          # DB 寫入邏輯
├── quality.py              # 資料品質驗證
├── query.py                # DB 查詢（inspect 用）
├── stock_master.py         # 股票主檔同步
├── official_calendar.py    # 官方交易日曆
├── calendar.py             # 交易日曆建構
├── http_client.py          # HTTP 客戶端（限速、重試）
├── logging_utils.py        # 日誌初始化
├── utils.py                # 通用工具函式
└── intraday/               # 日內策略模組（明日之星）
    ├── engine.py            # 日內策略掃描引擎
    ├── fetcher.py           # MIS 即時報價 API 客戶端
    ├── trades.py            # 模擬交易管理
    ├── snapshots.py         # 盤中量能快照
    ├── indicators.py        # 日內統計指標（勝率）
    ├── notifiers.py         # Telegram 通知
    └── scheduler.py         # APScheduler 排程器

config/
└── strategies.json          # 策略設定檔

tests/                       # 測試套件
data/                        # 資料目錄（不進 Git）
├── db/sentinel.db     # SQLite 資料庫
├── raw/fixtures/            # 離線測試 fixture
└── processed/               # 處理後 CSV 資料集

outputs/                     # 掃描、回測輸出
docs/                        # 文件
├── operation-manual.md      # 操作手冊（指令使用說明）
alembic/                     # DB 遷移
```

## 開發慣例

### 環境

- 一律在 `.venv` 虛擬環境中執行，指令前綴 `./.venv/bin/python`
- 環境變數放在 `.env`（不進 Git），格式參考 `.env.example`
- 所有 `TS_` 前綴的環境變數由 `config.py` 的 `Settings` 類自動讀取

### 程式碼風格

- 使用 `from __future__ import annotations` 支援型別提示
- 日誌使用 `logging.getLogger(__name__)` 搭配結構化 JSON 輸出
- DB 操作使用 SQLAlchemy ORM，Session 由 CLI 層建立並傳入
- 新增 CLI 指令在 `cli.py` 的 `build_parser()` 中註冊 subparser，邏輯放在對應模組
- 策略定義使用 JSON 設定檔 (`config/strategies.json`)，不硬編碼

### 資料庫

- 主鍵為 `(market, symbol)` 複合鍵，避免跨市場代碼衝突
- 使用 `create_schema(engine)` 確保 schema 存在（指令執行時自動補）
- 新增 model 定義在 `models.py`，使用 `DeclarativeBase`
- migration 由 Alembic 管理

### 測試

- 測試檔位於 `tests/` 目錄
- 執行測試：`make test` 或 `./.venv/bin/python -m pytest -q`
- 帶覆蓋率：`make test-cov`
- 可用 `unittest` 或 `pytest`
- Mock 外部 API 呼叫，不依賴網路

### MIS API 注意事項

- TWSE MIS API (`mis.twse.com.tw`) 的 `Content-Type` 回傳為 `text/html`，但內容實際為 JSON
- 不可單純依賴 `Content-Type` 判斷，需嘗試 `response.json()` 解析
- 手動新增交易時，`--market` 可省略，系統會自動從 Stock 表偵測

## 常用 CLI 指令

```bash
# 日線資料抓取與掃描
python -m sentinel run --market TWSE --market TPEX --start-date YYYY-MM-DD --end-date YYYY-MM-DD

# 回測
python -m sentinel backtest --start-date YYYY-MM-DD --end-date YYYY-MM-DD

# 日內策略掃描
python -m sentinel run-intraday --top 300 --min-gain 0.075

# 更新模擬交易（即時價格）
python -m sentinel update-intraday-trades --real-time --price-type last

# 手動新增交易（market 可省略，自動偵測）
python -m sentinel add-intraday-trade --symbol 2330 --price 100

# 資料庫狀態檢查
python -m sentinel inspect status
```

## 開發指令速查（Makefile）

```bash
make install-dev   # 安裝開發依賴 + pre-commit hooks
make format        # black + isort 格式化
make lint          # ruff linting
make type-check    # mypy 型別檢查
make check         # format + lint + type-check
make test          # pytest
make test-cov      # pytest + 覆蓋率報告
make init-db       # 初始化本地 SQLite 資料庫
make docker-up     # 啟動本地 PostgreSQL + TimescaleDB
make docker-down   # 停止 Docker 環境
```

## 重要文件

| 文件 | 用途 |
|------|------|
| `project.md` | 專案需求規格書（設計與驗收標準） |
| `docs/operation-manual.md` | 操作手冊（以此為準） |
| `config/strategies.json` | 策略設定檔 |
| `pyproject.toml` | 專案設定、工具設定集中在此 |
| `.env` | 環境變數（不進版控） |
| `scripts/` | 輔助腳本、一次性分析腳本（不進生產） |
