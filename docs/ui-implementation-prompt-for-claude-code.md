# Claude Code 實作提示詞（Sentinel UI）

請在專案 `/Users/ian-yu/git/sentinel` 內實作 Web UI，需求依據：
- `docs/ui-specification.md`（主規格，最高優先）
- `docs/ui-plan.md`（既有規劃，可參考但不得與主規格衝突）
- `docs/operation-manual.md`（CLI 功能定義來源）

## 你的任務
將 Sentinel 現有 CLI 功能完整映射到可操作 UI，並保留後續擴充能力。UI 必須避免 AI 感，採專業交易終端風格。

## 必要約束
1. 不可修改 `sentinel/*.py` 既有商業邏輯。
2. UI 執行任務必須透過既有 CLI（subprocess）或 DB 查詢，不可重寫策略/回測核心邏輯。
3. 所有新增程式碼需符合專案 black / ruff / mypy 基本要求。
4. 所有回覆、註解、commit message 使用繁體中文。

## 目標目錄
建立（或補齊）以下結構：

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

## 核心實作要求

### A. CommandSpec 抽象（最優先）
在 `ui/services/command_specs.py` 實作 declarative 規格，至少包含：
- `command_id`
- `argv_template`
- `fields`（name/type/required/default/options/help）
- `validator`
- `result_parser`
- `page_slot`

目標：新增 CLI 指令時，主要只需新增 spec。

### B. 表單工廠
在 `ui/components/form_factory.py` 依 spec 自動渲染表單，支援型別：
- `text`
- `number`
- `date`
- `select`
- `multiselect`
- `checkbox`
- `path`

### C. 任務執行器
在 `ui/services/command_runner.py` 實作：
- 短任務同步執行
- 長任務背景執行
- 任務狀態：`pending/running/success/failed`
- 保留 `argv`、`started_at`、`ended_at`、`exit_code`、`stdout/stderr tail`

### D. Command Preview
在每個可執行區塊中，執行前顯示唯讀 command preview，讓使用者可追溯。

### E. RWD 與風格
依 `docs/ui-specification.md`：
- Desktop / Tablet / Mobile 三斷點
- 專業交易終端風格
- 高密度表格、語義化顏色、非 SaaS 卡片模板感

## CLI 功能覆蓋清單（必須都有入口）
- `init-db`
- `sync-calendar`
- `sync-stocks`
- `sync`
- `yahoo-backfill`
- `run`
- `check-stock`
- `import-minute-bars`
- `backfill-intraday-aggregates`
- `backtest`
- `update-intraday-stats`
- `capture-intraday-snapshot`
- `run-intraday`
- `update-intraday-trades`
- `monitor-intraday-trades`
- `add-intraday-trade`
- `clear-intraday-trades`
- `scheduler`
- `inspect status`
- `inspect completeness`
- `inspect results`
- `inspect logs`
- `inspect intraday-trades`

## 分階段開發（照順序）

### Phase A（MVP）
1. `Overview`
2. `Task Center`
3. `Data Sync`
4. `Daily Scan`
5. `Inspect`

### Phase B
1. `Stock Check`
2. `Backtest`
3. `Strategies`（先唯讀 + 啟停，含備份與驗證）

### Phase C
1. `Intraday` 全功能
2. 手機監控優化（30 秒刷新）

## 最低測試要求
新增最小測試覆蓋：
- command builder（argv 組裝）
- validator（日期/數值/必要欄位）
- result parser（成功/失敗輸出解析）

## 驗收標準（DoD）
1. 所有 CLI 功能可在 UI 找到並執行。
2. 每個執行功能都提供 command preview。
3. 長任務不阻塞 UI，可在 Task Center 追蹤。
4. Desktop / Tablet / Mobile 無版面破裂。
5. 任務失敗可回看錯誤與 log tail。

## 輸出要求
請在完成後提供：
1. 變更檔案清單（含路徑）
2. 每頁功能對照表（CLI -> UI）
3. 已知限制與後續建議
4. 測試結果摘要
