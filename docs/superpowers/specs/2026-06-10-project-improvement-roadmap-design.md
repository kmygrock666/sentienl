# Sentinel 專案改善路線圖設計（2026-06-10）

## 目標

對 sentinel（台股策略選股系統）進行全面體質改善與功能擴充，分四個階段循序執行：
安全修復 → 效能優化 → 補完未完成功能 → 新增功能。每個任務獨立 commit、
通過 `make check` 與 `pytest` 後才進入下一項。

## 背景現況

- 核心套件 `sentinel/` 約 7,800 行（含 `intraday/` 子模組 1,160 行）、
  Streamlit UI `ui/` 約 8,800 行、測試 `tests/` 約 4,100 行。
- 日線管線（抓取 → 品質檢核 → 指標 → 策略掃描 → 輸出）與 UI Phase 1 已可運作。
- 已知問題：硬編碼 Telegram token、多處逐列迭代效能瓶頸、數個 `NotImplementedError`
  stub、UI Scheduler 控制未接線、`ui_tasks.json` 無限增長。

## Phase 0：基準點

把工作區現有未提交內容以 conventional commits 提交：

1. `feat(ui)`：完整 Streamlit 儀表板（`ui/`、`tests/ui/`、`.streamlit/`、`conftest.py`、
   `docs/ui-*.md`、README 與 pyproject 的 UI 章節/extras）。
2. `fix`：`persistence.py` 的 upsert 修正（price sync 不覆蓋 `industry`、
   `_upsert_stock_rows` 增加 `update_columns` 參數、`signals_json` 合併 `direction`）
   與 `intraday/engine.py` 的 `avg_v5` float 轉型。

`.agents/skills/`（外部安裝的 agent skills）不納入版本控制。

## Phase 1：安全修復

**移除硬編碼 Telegram token fallback**（`sentinel/intraday/scheduler.py`）：

- 憑證只從 `config.py`（pydantic-settings，`TS_` prefix 環境變數）讀取。
- 缺少憑證時記 log 警告並停用通知功能，排程本體照常運作。
- `.env.example` 補上 `TS_TELEGRAM_BOT_TOKEN`、`TS_TELEGRAM_CHAT_ID` 範例。
- 已進 git 歷史的 token 視同外洩，由使用者自行至 BotFather 重發（文件中註明）。

## Phase 2：效能優化與程式碼健康

行為不變的重構，靠既有測試保護；邏輯有變者先寫測試（TDD）。

1. **`persistence.py` 向量化**：`upsert_daily_prices`、`upsert_trading_calendar`
   的逐列型別轉換改為 pandas 向量化批次建構；`upsert_technical_indicators`
   的逐列 `apply()` 改 merge/isin；補齊 `trading_date` 等缺失型別註記。
2. **`quality.py` 向量化**：`_detect_price_spikes` 的 `iterrows()` 前收盤查找
   改為 groupby + shift。
3. **`indicators.py` 拆分**：286 行的 `_compute_group_indicators` 拆成數個
   聚焦小函式（均線群、震盪指標群、量能群、衍生欄位群）。
4. **`intraday/engine.py` 常數化**：漲幅門檻 0.03、量比 1.5、價格上限 1000
   等魔術數字抽成模組層級常數。
5. **`ui/services/command_runner.py` 任務檔清理**：`ui_tasks.json` 保留最近
   200 筆，寫入時自動修剪。

## Phase 3：補完未完成功能

1. **TPEX 日線解析器**：實作 `providers.py` 中 `NotImplementedError` 的解析邏輯，
   以離線 fixture 測試驅動。
2. **股票主檔／行事曆網路抓取**：實作 `stock_master.py` 與 `official_calendar.py`
   的 live 網路模式；fixture 測試為主，環境允許時做實連驗證。
3. **UI Scheduler 啟停控制接線**：Intraday 頁的 scheduler 表單經由
   `command_runner` 啟動/停止排程子行程，顯示目前狀態。
4. **分鐘級回測 CLI 整合**：`backtest_minute.py` 接上 CLI 子指令，並在
   `ui/services/command_specs.py` 註冊對應 CommandSpec。

## Phase 4：新增功能

1. **回測結果比較儀表板**：掃描 `outputs/backtests/` 既有結果目錄，
   UI 多選回測 run → 指標並排表（CAGR / MDD / 勝率）＋ Plotly 權益曲線疊圖。
   不更動資料庫 schema。
2. **策略規則編輯器**：擴充 `8_Strategies` 頁，以表單編輯策略條件，
   `jsonschema` 驗證後寫回 `config/strategies.json`，沿用既有 `.bak` 備份機制。
3. **即時持倉損益看板**：Intraday 頁對未平倉 `IntradayTrade` 以 `MISFetcher`
   取得即時報價，計算未實現損益、總損益指標卡，支援手動與自動刷新。
4. **主力買賣超（法人籌碼）**：
   - 新 provider 抓取 TWSE T86（三大法人買賣超）與 TPEX 對應端點。
   - 寫入既有未使用的 `InstitutionalFlow` 資料表。
   - 新 CLI 子指令 `sync-institutional` ＋ UI CommandSpec。
   - 衍生指標（如外資 5 日淨買超）供策略條件引用。
   - Stock Check 頁顯示個股籌碼資訊。
   - 離線 fixture 測試；需網路的部分在環境允許時實連驗證。

## 錯誤處理原則

- 網路 provider 沿用既有 retry / fixture fallback 模式。
- 通知類功能（Telegram）缺憑證時降級停用，不阻斷主流程。
- UI 操作失敗顯示使用者可讀訊息，詳細錯誤記入任務日誌。

## 測試策略

- 框架：pytest；行為變更先寫失敗測試再實作。
- 重構不改測試，靠既有套件驗證行為不變。
- 覆蓋率維持 `fail_under=60` 門檻，新增程式碼以 80% 為目標。
- 每階段完成跑 `make check`（black + isort + ruff + mypy）與全套 `pytest`。

## 執行順序與交付

Phase 0 → 1 → 2（5 個任務）→ 3（4 個任務）→ 4（4 個功能），
共約 15 個獨立 commit，皆遵循 conventional commits 格式。
