# Phase 3：補完未完成功能 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修復兩個既有測試失敗、補上 TPEX 日線解析器測試覆蓋、為 UI 加上 Scheduler 停止控制。

**Architecture:** 探索後修正範圍——TPEX 解析器、股票主檔/行事曆網路模式、分鐘級回測整合皆已存在；
本階段聚焦：(1) 測試修復與補強，(2) `command_runner.stop_task()` ＋ Intraday 頁接線。

**Tech Stack:** Python 3.9、pandas、pytest、Streamlit、APScheduler。

**驗證指令（每 Task 結尾）：** `.venv/bin/python -m pytest -q` 全綠（本階段後不再有排除清單）、
`black --check` / `ruff check` 對觸碰檔案乾淨。

---

### Task A: 修復 test_providers 日期不符＋補 TPEX 解析器測試

**Files:**
- Modify: `tests/test_providers.py`
- Create: `tests/fixtures/prices/tpex_daily_20260305.csv`（若選擇 fixture 形式）或直接 inline payload

**根因：** 測試 payload 標頭為「114年03月05日」（ROC 114 = 西元 2025），但測試以
`date(2026, 3, 5)` 呼叫，解析器日期驗證（providers.py `_parse_csv` 的
`market_data_date_not_match` 防護）正確地回傳空 DataFrame。**解析器行為正確，修測試。**

- [ ] **Step 1:** 將 `test_twse_parser_extracts_price_rows` 的 `trading_date` 改為 `date(2025, 3, 5)`，
  與 payload 的 114年 一致。跑 `pytest tests/test_providers.py -v` 確認轉綠。
- [ ] **Step 2:** 新增 `test_twse_parser_rejects_mismatched_date`：用同 payload 配
  `date(2026, 3, 5)` 呼叫，斷言回傳空 DataFrame（鎖住日期防護行為）。
- [ ] **Step 3:** 新增 TPEX 解析器測試 `test_tpex_parser_extracts_price_rows`，inline payload
  仿照 TPEX 實際格式（`providers.py` `TpexDailyPriceProvider._parse_csv` 預期格式）：

```
"資料日期:114/03/05"
"代號","名稱","收盤","漲跌","開盤","最高","最低","成交股數","成交金額(元)"
"8069","元太","250.00","+5.00","246.00","252.00","245.50","5,000,000","1,250,000,000"
"6488","環球晶","480.00","-2.00","482.00","485.00","478.00","3,000,000","1,440,000,000"
```

  以 `date(2025, 3, 5)` 呼叫 `TpexDailyPriceProvider()._parse_csv(payload, ...)`，斷言
  symbol/close/volume 正確、market 欄為 "TPEX"。實作前先閱讀 `_parse_csv` 與
  `_find_column` 確認欄名匹配方式，payload 欄名需與其候選詞相符。
- [ ] **Step 4:** 新增 `test_tpex_parser_rejects_mismatched_date`（同 Step 2 模式）。
- [ ] **Step 5:** `pytest tests/test_providers.py -v` 全綠 → commit：
  `fix(test): align provider test dates with ROC payload; add TPEX parser coverage`

### Task B: 修復股票主檔 ISIN 區段過濾

**Files:**
- Modify: `sentinel/stock_master.py`（`_parse_isin_html_stock_master` 一帶）
- Test: `tests/test_stock_master.py`（既有失敗測試轉綠，不改測試本身）

**根因：** `valid_sections = ["股票", "ETF", "受益"]` 讓 ETF 區段（如 0050）混入股票主檔，
而測試 `test_twse_stock_master_provider_parses_isin_html_stock_section` 期望只收「股票」區段。
測試代表意圖（策略掃描的主檔應為純股票；ETF 另由 `is_pure_stock` 指標層排除是雙保險）。

- [ ] **Step 1:** 先跑 `pytest tests/test_stock_master.py -v` 記錄現有失敗。
- [ ] **Step 2:** 閱讀 `_parse_isin_html_stock_master` 與其所有呼叫端、以及
  `tests/test_stock_master.py` 全部測試，確認沒有其他測試依賴 ETF/受益 區段被收錄。
  若有衝突測試，停下回報 BLOCKED。
- [ ] **Step 3:** 將區段過濾改為僅接受「股票」區段（保留參數化空間：
  `valid_sections: Sequence[str] = ("股票",)` 作為函式參數預設值，呼叫端不變）。
- [ ] **Step 4:** `pytest tests/test_stock_master.py tests/test_cli.py -q` 全綠 → commit：
  `fix: restrict ISIN stock-master parsing to the 股票 section`

### Task C: Scheduler 停止控制（stop_task ＋ UI 接線）

**Files:**
- Modify: `ui/services/command_runner.py`（新增 `stop_task`）
- Modify: `ui/pages/6_Intraday.py`（Scheduler 分頁加停止按鈕與狀態刷新）
- Test: `tests/ui/test_command_runner.py`

- [ ] **Step 1（TDD）:** 在 `tests/ui/test_command_runner.py` 新增：
  - `test_stop_task_terminates_running_process`：用 `launch_task` 跑一個長任務
    （直接構造 TaskRun + `subprocess.Popen(["sleep", "30"])` 較簡單；把 pid 寫入 task 並存檔），
    呼叫 `stop_task(task_id)`，斷言任務狀態變為 `"stopped"`、行程已不存在
    （`os.kill(pid, 0)` 拋 OSError/ProcessLookupError）。
  - `test_stop_task_noop_on_finished_task`：對 status="success" 的任務呼叫，斷言狀態不變。
  跑測試確認 ImportError（紅燈）。
- [ ] **Step 2:** 在 `command_runner.py` 實作：

```python
def stop_task(task_id: str) -> TaskRun:
    """終止執行中的任務：先 SIGTERM，2 秒後仍存活則 SIGKILL。"""
    task = _store.get(task_id)
    if task is None:
        raise ValueError(f"Task {task_id} not found")
    if task.status != "running" or not task.pid:
        return task

    import signal
    import time

    try:
        os.kill(task.pid, signal.SIGTERM)
        for _ in range(20):
            time.sleep(0.1)
            os.kill(task.pid, 0)  # 仍存活則拋例外跳出
        os.kill(task.pid, signal.SIGKILL)
    except (OSError, ProcessLookupError):
        pass  # 行程已結束

    task.status = "stopped"
    task.ended_at = datetime.utcnow().isoformat()
    task.stdout_tail = _read_tail(task.stdout_path)
    task.stderr_tail = _read_tail(task.stderr_path)
    _store.save(task)
    return task
```

  注意：`poll_task` 對非 "running" 狀態直接返回，"stopped" 不需額外處理；檢查
  Task Center / log_viewer 的狀態 badge 是否需認識 "stopped"（`ui/components/` 搜尋
  status 字串映射，補上即可）。
- [ ] **Step 3:** `ui/pages/6_Intraday.py` Scheduler 分頁（~277-299 行）：
  執行中時顯示「🛑 停止 Scheduler」按鈕 → `stop_task(task.task_id)` → `st.rerun()`；
  並在分頁頂部 `poll_all_running()` 後再過濾 scheduler 任務，確保狀態即時。
- [ ] **Step 4:** `pytest tests/ui/ -q` 全綠；`black --check`、`ruff check` 觸碰檔案乾淨。
- [ ] **Step 5:** Commit：`feat(ui): add stop control for resident scheduler tasks`

### Task D:（已完成，僅驗證）分鐘級回測整合

探索確認 `backtest --execution-model minute_bar` 已存在於 CLI（cli.py 768-805）、
CommandSpec（BACKTEST）與 UI（5_Backtest 執行回測分頁）。不新增程式碼（YAGNI）。

- [ ] **Step 1:** `.venv/bin/python -m sentinel backtest --help` 確認 `--execution-model`
  選項存在即視為通過，記錄於回報中。

---

## 完成定義

- `pytest`（不帶任何 ignore）全綠。
- Scheduler 可從 UI 啟動且可停止。
- 每 Task 獨立 commit。
