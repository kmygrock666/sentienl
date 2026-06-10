# Phase 4：新功能 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 四個新功能：回測比較儀表板、策略規則編輯器、即時持倉損益看板、主力買賣超資料導入。

**Architecture:** 各功能「邏輯層（純函式、可測試）→ UI 層（Streamlit）」分離；
邏輯層 TDD，UI 層以 `ast.parse` 與既有測試保護。每任務獨立 commit。

**Tech Stack:** Python 3.9、pandas、SQLAlchemy、Streamlit、Plotly、jsonschema、pytest。

**每 Task 結尾驗證：** `.venv/bin/python -m pytest -q` 全綠；black/ruff 對觸碰檔案乾淨；
UI 頁面 `ast.parse` 通過。

---

### Task 4a: 回測結果比較儀表板

**Files:**
- Create: `ui/services/backtest_compare.py`、`tests/ui/test_backtest_compare.py`
- Modify: `ui/pages/5_Backtest.py`（新增「比較」分頁）

**資料來源：** `outputs/backtests/<run_dir>/`，run_dir 形如 `2024-01-01_2026-03-24` 或
`minute_...`；內含 `report.csv`（欄位 strategy_id, strategy_name, trades, win_rate,
avg_trade_return, total_return, cagr, mdd, ...）、`trades.csv`（含 exit_date, balance,
trade_return, strategy_id）、`metadata.json`。

- [ ] **邏輯層（TDD）** `ui/services/backtest_compare.py`：
  - `discover_backtest_runs(backtests_dir: Path) -> list[dict]`：列出含 report.csv 的
    run 目錄，回傳 `{"run_id": 目錄名, "path", "metadata": dict|None}`，按 mtime 新→舊。
  - `load_run_report(path: Path) -> pd.DataFrame`：讀 report.csv 並附 `run_id` 欄。
  - `build_equity_curves(trades: pd.DataFrame) -> pd.DataFrame`：依 strategy_id 分組、
    按 exit_date 排序，輸出 long-format `[strategy_id, exit_date, balance]`（balance 缺值
    時以 (1+trade_return) 累乘 × 100000 重建）。
  - 測試：tmp_path 造 2 個假 run 目錄驗證 discovery 排序、report 載入、曲線重建
    （含無 balance 欄的 fallback）。
- [ ] **UI 層** `5_Backtest.py` 新增第 4 個分頁「📊 比較」：multiselect 選 2+ runs →
  指標並排表（pd.concat 各 run report，欄 run_id+strategy+cagr/mdd/win_rate/total_return）
  → Plotly 權益曲線疊圖（每 run×strategy 一條線，go.Scatter，沿用 charts.py 的暗色模板）。
- [ ] Commit: `feat(ui): add backtest comparison dashboard with equity curve overlay`

### Task 4b: 策略規則編輯器

**Files:**
- Create: `ui/services/strategy_editor.py`、`tests/ui/test_strategy_editor.py`
- Modify: `ui/pages/8_Strategies.py`

**現況：** 8_Strategies 已有 is_active 切換＋`.bak` 備份（`_save_raw`）＋唯讀 JSON 檢視。
條件 schema：`{name, field, operator(>,>=,<,<=,==,!=), target XOR value, multiplier?,
consecutive_days?}`，巢狀於 `params_json.conditions`。

- [ ] **邏輯層（TDD）** `ui/services/strategy_editor.py`：
  - `CONDITION_SCHEMA` / `STRATEGY_SCHEMA`（jsonschema dict；operator enum、target/value
    oneOf 擇一、multiplier number、consecutive_days int≥1）。
  - `validate_conditions(conditions: list[dict]) -> list[str]`：回傳人類可讀錯誤清單
    （空清單 = 合法）。用 jsonschema `Draft202012Validator.iter_errors` 收集。
  - `apply_condition_edits(raw_config: dict, strategy_id: str, conditions: list[dict]) -> dict`：
    回傳**新** config（深拷貝，不變異原 dict），在 long/short_strategies 中定位
    strategy_id 並替換其 `params_json.conditions`；找不到時 raise ValueError。
  - 測試：合法/非法 operator、target+value 同時存在、缺 field、apply 後原 dict 未變異、
    未知 strategy_id。
- [ ] **UI 層** `8_Strategies.py`：詳情區塊加「✏️ 編輯條件」expander —
  `st.data_editor`（num_rows="dynamic"）編輯該策略 conditions（欄：name/field/operator/
  target/value/multiplier/consecutive_days），儲存前 `validate_conditions`，錯誤顯示
  `st.error` 不寫檔；通過則沿用既有 `_save_raw`（自動 .bak）寫回並 `st.rerun()`。
  注意 data_editor 回傳的 NaN/None 欄位要清除（target 與 value 擇一保留）。
- [ ] Commit: `feat(ui): add strategy condition editor with jsonschema validation`

### Task 4c: 即時持倉損益看板

**Files:**
- Modify: `sentinel/intraday/trades.py`（新增純邏輯函式）、`ui/pages/6_Intraday.py`
- Test: `tests/test_intraday_trades.py`（新建或併入既有）

**素材：** `IntradayTrade`（models.py:248-265，entry_price Numeric、status open/closed、
shares）；`MISFetcher.fetch_all(symbols, markets)` ＋ `parse_mis_data(msg)` →
`{symbol, market, close, prev_close, ...}`；UI 既有 `get_intraday_trades(engine, status="open")`。

- [ ] **邏輯層（TDD）** `sentinel/intraday/trades.py` 新增：

```python
def compute_open_trades_pnl(session, quotes_fetcher=None):
    """計算未平倉部位即時損益。quotes_fetcher 可注入測試替身。

    回傳 list[dict]：symbol, market, name, entry_date, entry_price, current_price,
    unrealized_pct, unrealized_amount（(現價-進場價)*shares）。
    無未平倉或抓不到報價的部位以 current_price=None 呈現。
    """
```

  預設 quotes_fetcher 用 `MISFetcher().fetch_all` ＋ `parse_mis_data`；測試注入 fake
  fetcher 回傳固定報價，驗證漲跌計算、缺報價容錯、空持倉回傳 []。
- [ ] **UI 層** `6_Intraday.py` 模擬交易分頁「目前持倉」區：加「🔄 更新即時損益」按鈕 →
  呼叫 `compute_open_trades_pnl`（結果存 session_state）→ 顯示總未實現損益 metric ＋
  per-trade 表（現價、未實現%著色）。MIS 抓取較慢（每批 50 檔 sleep 2s）→ 按鈕觸發即可，
  不做自動刷新。
- [ ] Commit: `feat: add live unrealized P&L board for open intraday positions`

### Task 4d: 主力買賣超（法人籌碼）導入

**Files:**
- Create: `sentinel/institutional.py`、`tests/test_institutional.py`
- Modify: `sentinel/persistence.py`（upsert）、`sentinel/cli.py`（sync-institutional）、
  `ui/services/command_specs.py`、`ui/pages/2_Data_Sync.py`、
  `ui/services/queries.py` ＋ `ui/pages/4_Stock_Check.py`（顯示）

**既有資源：** `InstitutionalFlow`（models.py:102-112：market/symbol/trading_date PK，
foreign_net / investment_trust_net / dealer_net / total_net，全 Integer）已建表未使用。
Provider 模式（fixture/network/auto、retry、rate-limit）照 `providers.py` 抄。

分兩個 commit：

**(1) Provider ＋ 持久化 ＋ CLI**
- [ ] `sentinel/institutional.py`：`TwseT86Provider`（endpoint
  `https://www.twse.com.tw/rwd/zh/fund/T86`，params `date=YYYYMMDD&selectType=ALLBUT0999&response=csv`）
  與 `TpexInstitutionalProvider`（endpoint
  `https://www.tpex.org.tw/web/stock/3insti/daily_trade/3itrade_hedge_result.php`，
  params `l=zh-tw&o=csv&se=EW&t=D&d=ROC/MM/DD`）。解析用 `_find_column` 式的容錯欄名
  比對（外資/外陸資、投信、自營商、三大法人 各取「買賣超」股數欄），輸出欄：
  market, symbol, trading_date, foreign_net, investment_trust_net, dealer_net, total_net。
  fixture 前綴 `twse_t86` / `tpex_inst`（目錄 `fixtures/institutional/`）。
  日期驗證與 providers.py 同精神（mismatch → 空 frame ＋ warning）。
- [ ] `persistence.py`：`upsert_institutional_flows(session, flows: pd.DataFrame) -> int`
  （向量化建 rows，走 `_upsert_rows`，conflict=PK 三欄，update=四個 net 欄）；
  `table_to_model` 加入 `"institutional_flows": InstitutionalFlow`。
- [ ] `cli.py`：`sync-institutional --date YYYY-MM-DD [--market TWSE --market TPEX]
  [--source-mode auto] [--database-url ...]`，仿 sync-stocks handler：fetch → upsert →
  log 筆數。
- [ ] 測試（TDD）：inline payload 測兩個 parser（含日期 mismatch 案例）、
  upsert 寫入 sqlite 後讀回驗證、CLI fixture-mode 煙霧測試（仿 test_cli.py 模式，可選）。
- [ ] Commit: `feat: add institutional flow (T86) providers, persistence and sync CLI`

**(2) UI 接入**
- [ ] `command_specs.py`：`SYNC_INSTITUTIONAL` CommandSpec（date/market/source-mode 欄位，
  page_slot="data_sync"），加入 ALL_SPECS；`2_Data_Sync.py` 仿既有區塊加表單。
- [ ] `queries.py`：`get_institutional_flow(engine, market, symbol, days=10) -> pd.DataFrame`
  （近 N 筆，中文欄名：日期/外資/投信/自營商/合計）。
- [ ] `4_Stock_Check.py`：結果區下方加「法人籌碼」區塊 — 查無資料顯示提示，有資料顯示
  近 10 日表格＋外資連買天數 metric。
- [ ] Commit: `feat(ui): expose institutional flow sync and per-stock display`

**範圍外（記錄於 spec，後續再做）：** 把法人欄位合併進指標 frame 供策略條件引用 —
需動 pipeline，與本任務解耦。

---

## 完成定義

全套 pytest 綠、每功能可在 UI 操作、五個 commit、最後做整體最終審查。
