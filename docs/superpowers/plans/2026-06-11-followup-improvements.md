# 後續改善 Implementation Plan（retry 整併＋法人指標進策略）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** (R1) 把三份近重複的網路 fetch/retry 迴圈抽成共用 helper；(R2) 法人買賣超欄位
（含衍生 5 日滾動值）合併進指標 frame，讓策略條件可直接引用，`run` 與 `check-stock` 皆支援。

**Architecture:** R1 是行為不變重構＋新增 retry helper 單元測試；R2 仿 3D 聚合棒的
enrichment 前例（pipeline.compute_indicators 維持純函式，DB 載入與 merge 在 cli 層注入），
邏輯放 `sentinel/institutional.py` 純函式、TDD。

---

### Task R1: 共用 fetch/retry helper

**Files:** Modify `sentinel/providers.py`、`sentinel/institutional.py`；Test `tests/test_providers.py`

- 在 `providers.py` 新增模組層級：
  - `_rate_limit(settings)`（搬移自三個 class 的同名方法，邏輯不變）
  - `fetch_csv_with_retry(endpoint, params, headers, settings, market, trading_date, parse_fn, success_event) -> pd.DataFrame`
    —— 內容為現有三份 retry 迴圈的逐字共通版本：每次嘗試先 `_rate_limit`，`fetch_text`
    → `parse_fn(payload, trading_date)` → log success_event（含 rows），例外組
    `(requests.RequestException, ValueError, RuntimeError, subprocess.CalledProcessError)`
    記 `fetch_retry`、指數退避＋jitter，`max_retries` 用盡 raise RuntimeError from last_error。
- 三個 `fetch_day`（TwseDailyPriceProvider、TpexDailyPriceProvider、InstitutionalFlowProvider）
  的 fixture 分支保留，網路分支改呼叫共用 helper；刪除各 class 的 `_rate_limit`。
- 測試（先寫紅燈）：monkeypatch `providers.fetch_text` —— (a) 失敗兩次後成功 → 回傳
  frame 且重試兩次；(b) 全失敗 → RuntimeError；(c) settings.max_delay_seconds=0 時不 sleep
  （monkeypatch time.sleep 計數，退避 sleep 另計）。
- 全套測試不變綠；commit：`refactor: consolidate provider fetch/retry loops into shared helper`

### Task R2: 法人欄位進指標 frame

**Files:** Modify `sentinel/institutional.py`、`sentinel/cli.py`；Test `tests/test_institutional.py`

- `sentinel/institutional.py` 新增純函式（TDD）：
  - `load_institutional_frame(session, start_date, end_date) -> pd.DataFrame`：select
    InstitutionalFlow 日期區間 → columns [market, symbol, trading_date, foreign_net,
    investment_trust_net, dealer_net, total_net]，空結果回空 frame（含欄位）。
  - `enrich_with_institutional(frame, flows) -> pd.DataFrame`：以
    (market, symbol, trading_date) left-merge（雙邊日期正規化為 date），再依
    (market, symbol) 按日期排序計算 `foreign_net_5d`（rolling 5 sum，min_periods=1）與
    `foreign_buy_streak`（連續 foreign_net>0 天數，向量化或 groupby apply 皆可）。
    flows 為空時回傳原 frame 加上全 NaN 欄（欄位永遠存在，策略引用不會 KeyError）。
- `cli.py`：
  - `run` handler 在 `compute_indicators` 之後、`scan_strategy` 之前：若有 engine，開
    Session 以 frame 的日期範圍呼叫 load + enrich，try/except 包覆（失敗 log warning、
    照常掃描）；log enriched 命中筆數。
  - `check-stock`：新增 `--database-url`（fallback TS_DATABASE_URL，皆無則跳過 enrichment），
    同樣在 compute_indicators 後 enrich。
- 測試：in-memory sqlite 寫入數日 flows → load 區間正確；enrich 後欄位齊備、5 日滾動值
  與連買天數手算驗證、無 flows 時欄位存在且 NaN、原 frame 未變異（回傳新 frame）。
- commit：`feat: surface institutional flow columns to strategy conditions`

### Task R3: .gitignore `.agents/`（已完成，獨立 commit）

## 完成定義
全套 pytest 綠；R1 後三個 provider 網路路徑共用同一份迴圈；R2 後策略 JSON 可寫
`{"field": "foreign_net_5d", "operator": ">", "value": 0}` 之類條件並在 run/check-stock 生效。
