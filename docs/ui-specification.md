# Sentinel Web UI 規格書（交付 Claude Code 實作）

> 版本：v1.0  
> 日期：2026-05-10  
> 適用專案：`/Users/ian-yu/git/sentinel`  
> 目的：將現有 CLI 全功能映射為可操作的 Web UI，並保留後續擴充能力。

---

## 1. 目標與設計原則

### 1.1 產品目標
- 將 Sentinel 現有 CLI 操作（含日線、回測、日內、檢查）完整搬到 UI。
- 降低指令記憶與人工排錯成本，保留專業交易工具感。
- 同時支援桌面版與行動版操作，手機以監控/查詢優先。

### 1.2 設計原則（避免 AI 感）
- 風格定位：專業交易終端，不採通用 SaaS 卡片風。
- 資訊優先：高密度但可掃讀，重要指標一眼可見。
- 可追溯：每次執行保留參數快照、指令預覽、日誌、輸出連結。
- 可擴充：新增 CLI 指令時不需重做頁面結構。

### 1.3 非目標（本期不做）
- 不改動既有 CLI 邏輯與策略計算邏輯。
- 不做多人權限與帳號系統（本機單人使用情境）。
- 不做雲端部署與分散式任務系統（先以 localhost 為主）。

---

## 2. 技術與架構約束

### 2.1 技術選型
- UI 框架：Streamlit（延續現有 `docs/ui-plan.md` 決策）
- 圖表：Plotly
- 資料來源：SQLite / PostgreSQL（透過 SQLAlchemy）
- 任務執行：`subprocess` + JobRun 輪詢

### 2.2 架構要求
- UI 不直接重寫商業邏輯，僅呼叫 CLI 或讀 DB。
- 長任務（>5秒）必須進入背景執行，UI 不阻塞。
- 所有查詢函式回傳 `pd.DataFrame`，空結果不拋例外。
- 所有設定檔寫入採「先備份、後驗證、再覆蓋」。

### 2.3 建議目錄

```text
ui/
├── app.py
├── pages/
│   ├── 1_Overview.py
│   ├── 2_Data_Sync.py
│   ├── 3_Daily_Scan.py
│   ├── 4_Stock_Check.py
│   ├── 5_Backtest.py
│   ├── 6_Intraday.py
│   ├── 7_Inspect.py
│   ├── 8_Strategies.py
│   └── 9_Task_Center.py
├── components/
│   ├── form_factory.py
│   ├── command_preview.py
│   ├── result_table.py
│   ├── log_viewer.py
│   └── layout.py
└── services/
    ├── db.py
    ├── command_runner.py
    ├── command_specs.py
    ├── queries.py
    └── parsers.py
```

---

## 3. 視覺設計系統

### 3.1 色彩（CSS variables）
- `--bg-0: #111417`（主背景）
- `--bg-1: #1A1F24`（面板背景）
- `--line: #2B343D`（分隔線）
- `--text-0: #E6E9EC`（主文字）
- `--text-1: #9AA6B2`（次文字）
- `--up: #D84B4B`（上漲/風險）
- `--down: #3FA66B`（下跌/獲利）
- `--warn: #E0A94A`（警示）
- `--accent: #3D6E8F`（互動重點）

### 3.2 字體
- 中文/英文正文：`IBM Plex Sans TC`
- 數字、代碼、時間：`JetBrains Mono`

### 3.3 元件語氣
- 按鈕：扁平、直角小圓角（4px），避免膠囊風。
- 表格：固定表頭、可排序、欄位密度高。
- 標籤：Long/Short/Warning 使用固定顏色語義。

---

## 4. RWD 規範

### 4.1 斷點
- Desktop：`>= 1024px`
- Tablet：`768px ~ 1023px`
- Mobile：`< 768px`

### 4.2 佈局策略
- Desktop：左側導覽 + 右側雙欄（參數/結果）。
- Tablet：導覽可收合，主區單欄區塊化。
- Mobile：底部 Tab（總覽、掃描、日內、任務、更多）。

### 4.3 行動優先功能
- 可執行：常用任務啟動、狀態檢視、結果查詢。
- 弱化：大批量參數編輯、複雜策略條件修改。

---

## 5. 功能地圖（CLI -> UI）

### 5.1 系統/同步
- `init-db` -> [資料同步] 初始化資料庫
- `sync-calendar` -> [資料同步] 行事曆同步
- `sync-stocks` -> [資料同步] 股票主檔同步
- `sync` -> [資料同步] 自動補齊股價
- `yahoo-backfill` -> [資料同步] Yahoo 補資料

### 5.2 日線/策略
- `run` -> [日線掃描] 執行完整 Pipeline
- `check-stock` -> [個股檢驗] 訊號逐條檢核

### 5.3 回測
- `import-minute-bars` -> [回測中心] 匯入分鐘線
- `backfill-intraday-aggregates` -> [回測中心] 補聚合資料
- `backtest` -> [回測中心] 執行回測

### 5.4 日內
- `update-intraday-stats`
- `capture-intraday-snapshot`
- `run-intraday`
- `update-intraday-trades`
- `monitor-intraday-trades`
- `add-intraday-trade`
- `clear-intraday-trades`
- `scheduler`

### 5.5 檢查
- `inspect status`
- `inspect completeness`
- `inspect results`
- `inspect logs`
- `inspect intraday-trades`

---

## 6. 頁面詳細規格

## 6.1 Overview
- 目的：提供全域健康狀態與快捷入口。
- 區塊：
  - 今日資料新鮮度（daily_prices 最新交易日、intraday 最新快照時間）
  - 最近 10 次 JobRun（成功/失敗/耗時）
  - 策略命中摘要（近 5 個交易日）
  - 快速操作（Run、Sync、Run Intraday）

## 6.2 Data Sync
- 功能群組：`init-db`, `sync-calendar`, `sync-stocks`, `sync`, `yahoo-backfill`
- 每個群組包含：
  - 參數表單
  - Command Preview（唯讀）
  - Run 按鈕
  - 執行中狀態 + log tail
  - 成功後輸出摘要（筆數/時間區間）

## 6.3 Daily Scan
- 功能：`run`
- 必填：`start-date`, `end-date`
- 常用可選：`market[]`, `trading-date`, `strategy-path`, `direction`
- 結果：
  - scan_results 表格
  - 依策略/方向/市場篩選
  - TradingView txt 匯出按鈕

## 6.4 Stock Check
- 功能：`check-stock`
- 輸入：`symbol`（必填）, `date`, `signal-path`, `dataset-path`
- 結果呈現：
  - 做多訊號（觸發/未觸發）
  - 警示訊號
  - 需盤中資料/待實作清單（不可自動檢驗）

## 6.5 Backtest
- 功能：`import-minute-bars`, `backfill-intraday-aggregates`, `backtest`
- backtest 表單欄位：
  - `start-date`, `end-date`, `execution-model`, `strategy-mode`
  - `symbol`, `initial-capital`, `position-size`
- 結果：
  - KPI（總報酬、CAGR、MDD、勝率）
  - 報表下載（`report.csv`, `trades.csv`）

## 6.6 Intraday
- 功能：日內所有指令
- 區塊：
  - 盤中快照（可每 30 秒自動刷新）
  - 明日之星掃描
  - 模擬交易監控（停利停損觸發）
  - 手動新增/清空交易
  - Scheduler 啟停與心跳

## 6.7 Inspect
- 子頁籤：`status`, `completeness`, `results`, `logs`, `intraday-trades`
- 支援：篩選、排序、CSV 匯出

## 6.8 Strategies
- 編輯檔：`config/strategies.json`
- 功能：
  - 策略啟停 (`is_active`)
  - 條件欄位檢視（先唯讀，第二階段再編輯）
  - 儲存前自動備份 `.bak`
  - JSON schema 驗證失敗即回滾

## 6.9 Task Center
- 全域工作佇列：執行中/成功/失敗
- 每筆任務展示：
  - 任務 ID
  - 指令
  - 參數快照
  - 開始/結束時間
  - Exit code
  - 日誌與錯誤堆疊
- 支援：重跑同參數

---

## 7. 通用互動與錯誤處理

### 7.1 表單驗證
- 日期格式統一 `YYYY-MM-DD`。
- `start-date <= end-date` 前端先擋。
- 數值欄位提供上下限與步進。

### 7.2 指令執行
- 任何任務提交前都顯示 command preview。
- 執行中可查看尾端日誌（最後 N 行）。
- 失敗時顯示可讀錯誤（對應 argparse error）。

### 7.3 狀態一致性
- 任務成功後刷新對應查詢快取。
- 任務失敗不覆蓋先前成功結果。

---

## 8. 可擴充規格（核心）

### 8.1 CommandSpec 抽象

每個 CLI 指令以 declarative spec 定義：
- `command_id`
- `argv_template`
- `fields`（name/type/required/default/options）
- `validator`
- `result_parser`
- `page_slot`

### 8.2 Form Factory
- 依 `fields` 自動渲染 Streamlit 表單。
- 支援欄位型別：`text`, `number`, `date`, `select`, `multiselect`, `checkbox`, `path`。

### 8.3 執行器
- 同步短任務：前台執行。
- 長任務：背景執行並寫入 JobRun（或本地任務表）。
- 解析 stdout/stderr 存於任務紀錄，供 UI 查詢。

---

## 9. 資料模型（UI 層）

### 9.1 TaskRun（建議）
- `id` (uuid)
- `command_id`
- `argv` (json/text)
- `status` (`pending/running/success/failed`)
- `started_at`, `ended_at`
- `exit_code`
- `stdout_tail`, `stderr_tail`
- `error_message`

### 9.2 UI Preference（可選）
- 最近使用參數快取（每個 command_id 一份）
- 最後選擇市場/日期範圍

---

## 10. 驗收標準（Definition of Done）

### 10.1 功能覆蓋
- 所有 CLI 指令皆可在 UI 找到入口並可執行。
- 每個執行功能皆有 command preview。

### 10.2 桌機/行動相容
- Desktop / Tablet / Mobile 三斷點無版面破裂。
- 手機上可完成：
  - 啟動 `run-intraday`
  - 檢視 `inspect results`
  - 追蹤任務狀態

### 10.3 可用性
- 長任務不阻塞 UI。
- 失敗任務可回看日誌與錯誤訊息。

### 10.4 程式品質
- 新增 UI 程式碼符合 black/ruff/mypy 基本要求。
- 關鍵流程具最小測試（command builder、validator、parser）。

---

## 11. 實作階段建議

### Phase A（MVP）
- Overview, Data Sync, Daily Scan, Inspect, Task Center

### Phase B
- Stock Check, Backtest, Strategies（含安全寫回）

### Phase C
- Intraday 全功能 + mobile 監控優化 + Telegram 觸發顯示

---

## 12. 交付給 Claude Code 的實作指令

請 Claude Code 依下列順序執行：
1. 建立 `ui/` 基礎目錄與 `services/command_specs.py` 抽象。
2. 先完成 `Overview + Task Center + Data Sync`。
3. 接著完成 `Daily Scan + Inspect`，確認核心查詢可用。
4. 最後完成 `Backtest + Intraday + Stock Check + Strategies`。
5. 每個頁面完成後，補最小可執行測試與操作說明。

必要約束：
- 不修改既有 `sentinel/*.py` 商業邏輯。
- 以既有 CLI 為唯一執行入口。
- 所有回覆與註解使用繁體中文。
