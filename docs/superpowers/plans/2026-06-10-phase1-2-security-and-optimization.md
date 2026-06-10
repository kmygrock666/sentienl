# Phase 1＋2：安全修復與效能優化 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 移除硬編碼 Telegram 憑證，並向量化 persistence/quality 熱路徑、抽出魔術數字、拆分過大函式、加上 UI 任務檔保留上限。

**Architecture:** 全部是對既有模組的原地改善：行為不變的重構靠既有 pytest 套件保護，行為有變的（通知降級、任務檔修剪）先寫失敗測試再實作。每個 Task 一個 commit。

**Tech Stack:** Python 3.9、pandas、SQLAlchemy 2.x、pydantic-settings、pytest、Streamlit。

**驗證指令（每個 Task 結尾都要跑）：**
```bash
.venv/bin/python -m pytest -q          # 全套測試
make check                              # black + isort + ruff + mypy（若環境沒有 make，逐一跑）
```

---

### Task 1: 移除硬編碼 Telegram token（Phase 1）

**Files:**
- Modify: `sentinel/intraday/scheduler.py:30-44`
- Modify: `.env.example`
- Test: `tests/test_intraday_scheduler.py`（新建）

- [ ] **Step 1: 寫失敗測試**

建立 `tests/test_intraday_scheduler.py`：

```python
import pytest

from sentinel.config import Settings
from sentinel.intraday.scheduler import IntradayScheduler


@pytest.mark.unit
def test_notifier_disabled_without_credentials(monkeypatch):
    """缺少 Telegram 憑證時不得 fallback 到任何內建 token，通知功能應停用。"""
    monkeypatch.setattr(
        "sentinel.intraday.scheduler.Settings",
        lambda: Settings(_env_file=None, tg_token=None, tg_chat_id=None),
    )
    scheduler = IntradayScheduler("sqlite://")
    assert scheduler.notifier is None


@pytest.mark.unit
def test_notifier_enabled_with_credentials(monkeypatch):
    monkeypatch.setattr(
        "sentinel.intraday.scheduler.Settings",
        lambda: Settings(_env_file=None, tg_token="test-token", tg_chat_id="123"),
    )
    scheduler = IntradayScheduler("sqlite://")
    assert scheduler.notifier is not None


@pytest.mark.unit
def test_no_hardcoded_token_in_source():
    """確保洩漏過的 token 片段不再出現在原始碼。"""
    import inspect
    import sentinel.intraday.scheduler as mod

    source = inspect.getsource(mod)
    assert "5675544561" not in source
    assert "-5018674933" not in source
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `.venv/bin/python -m pytest tests/test_intraday_scheduler.py -v`
Expected: `test_notifier_disabled_without_credentials` 與 `test_no_hardcoded_token_in_source` FAIL（目前有 fallback token）。

- [ ] **Step 3: 實作**

`sentinel/intraday/scheduler.py` 第 31-44 行改為：

```python
        # Configure notifier if settings available
        self.notifier = None
        token = self.settings.tg_token
        chat_id = self.settings.tg_chat_id

        if token and chat_id:
            self.notifier = TelegramNotifier(token, chat_id)
        else:
            logger.warning(
                "Telegram credentials not configured (TS_TG_TOKEN / TS_TG_CHAT_ID); "
                "notifications disabled."
            )
```

`.env.example` 結尾加上：

```
# Telegram 通知（盤中排程使用）。未設定時通知功能自動停用。
# TS_TG_TOKEN=123456:your-bot-token
# TS_TG_CHAT_ID=-100123456789
```

- [ ] **Step 4: 跑測試確認通過**

Run: `.venv/bin/python -m pytest tests/test_intraday_scheduler.py -v`
Expected: 3 PASS。再跑全套 `.venv/bin/python -m pytest -q` 確認無回歸。

- [ ] **Step 5: Commit**

```bash
git add sentinel/intraday/scheduler.py .env.example tests/test_intraday_scheduler.py
git commit -m "fix(security): remove hardcoded Telegram credentials fallback"
```

> 注意：舊 token 已存在於 git 歷史，視同外洩。提醒使用者至 BotFather 重發 token。

---

### Task 2: persistence.py 向量化＋型別註記（Phase 2）

**Files:**
- Modify: `sentinel/persistence.py`
- Test: 既有 `tests/test_db.py`（行為不變，靠它保護）

- [ ] **Step 1: 先跑既有測試建立基準**

Run: `.venv/bin/python -m pytest tests/test_db.py -q`
Expected: 全 PASS（記下數量）。

- [ ] **Step 2: 向量化 `upsert_daily_prices`（取代 213-229 行的逐列迴圈）**

```python
def upsert_daily_prices(session: Session, prices: pd.DataFrame, data_version: str) -> int:
    if prices.empty:
        return 0

    frame = prices[
        ["market", "symbol", "trading_date", "open", "high", "low", "close", "volume", "turnover"]
    ].copy()
    frame["trading_date"] = pd.to_datetime(frame["trading_date"]).dt.date
    for column in ("open", "high", "low", "close"):
        frame[column] = frame[column].astype(float)
    frame["volume"] = frame["volume"].astype(int)
    turnover = pd.to_numeric(frame["turnover"], errors="coerce")
    frame["turnover"] = [int(v) if pd.notna(v) else None for v in turnover]
    frame["adjusted_close"] = frame["close"]
    frame["data_version"] = data_version
    frame["updated_at"] = datetime.utcnow()
    rows = frame.to_dict(orient="records")

    _upsert_rows(
        session=session,
        table=DailyPrice.__table__,
        rows=rows,
        conflict_columns=["market", "symbol", "trading_date"],
        update_columns=[
            "open",
            "high",
            "low",
            "close",
            "volume",
            "turnover",
            "adjusted_close",
            "data_version",
            "updated_at",
        ],
    )
    return len(rows)
```

- [ ] **Step 3: `upsert_technical_indicators` 改 merge 過濾（取代 255-296 行）**

```python
def upsert_technical_indicators(
    session: Session, indicators: pd.DataFrame, prices: pd.DataFrame
) -> int:
    if indicators.empty or prices.empty:
        return 0

    keys = prices[["market", "symbol", "trading_date"]].copy()
    keys["trading_date"] = pd.to_datetime(keys["trading_date"]).dt.date
    keys = keys.drop_duplicates()

    filtered = indicators.copy()
    filtered["trading_date"] = pd.to_datetime(filtered["trading_date"]).dt.date
    filtered = filtered.merge(keys, on=["market", "symbol", "trading_date"], how="inner")
    if filtered.empty:
        return 0

    now = datetime.utcnow()
    rows: List[Dict[str, Any]] = []
    for column_name, spec in INDICATOR_SPECS.items():
        if column_name not in filtered.columns:
            continue
        subset = filtered.loc[
            filtered[column_name].notna(), ["market", "symbol", "trading_date", column_name]
        ]
        if subset.empty:
            continue
        chunk = pd.DataFrame(
            {
                "market": subset["market"],
                "symbol": subset["symbol"],
                "trading_date": subset["trading_date"],
                "indicator_name": str(spec["indicator_name"]),
                "params_hash": _hash_indicator_params(spec["params"]),
                "calc_version": DEFAULT_INDICATOR_VERSION,
                "value": subset[column_name].astype(float),
                "source_field": str(spec["source_field"]),
                "updated_at": now,
            }
        )
        rows.extend(chunk.to_dict(orient="records"))

    _upsert_rows(
        session=session,
        table=TechnicalIndicator.__table__,
        rows=rows,
        conflict_columns=[
            "market",
            "symbol",
            "trading_date",
            "indicator_name",
            "params_hash",
            "calc_version",
        ],
        update_columns=["value", "source_field", "updated_at"],
    )
    return len(rows)
```

- [ ] **Step 4: 向量化 `upsert_trading_calendar`（取代 392-402 行）**

```python
def upsert_trading_calendar(session: Session, trading_calendar: pd.DataFrame) -> int:
    if trading_calendar.empty:
        return 0

    frame = trading_calendar[["exchange", "calendar_date", "is_trading_day", "reason"]].copy()
    frame["calendar_date"] = pd.to_datetime(frame["calendar_date"]).dt.date
    frame["is_trading_day"] = frame["is_trading_day"].astype(bool)
    frame["updated_at"] = datetime.utcnow()
    rows = frame.to_dict(orient="records")

    _upsert_rows(
        session=session,
        table=TradingCalendar.__table__,
        rows=rows,
        conflict_columns=["exchange", "calendar_date"],
        update_columns=["is_trading_day", "reason", "updated_at"],
    )
    return len(rows)
```

- [ ] **Step 5: 補型別註記**

檔案頂部 import 增加 `from datetime import date, datetime` 與 `Union`，新增型別別名：

```python
DateLike = Union[str, "date", datetime, pd.Timestamp]
```

三個簽名補上：
- `persist_pipeline_results(..., trading_date: DateLike, ...)`（94 行）
- `upsert_scan_results(..., trading_date: DateLike, ...)`（337 行）
- `update_aggregated_bars(session: Session, market: str, trading_date: DateLike, prices: pd.DataFrame) -> None`（547 行）
- `_to_date(value: DateLike) -> date`（595 行）

- [ ] **Step 6: 跑測試確認行為不變**

Run: `.venv/bin/python -m pytest tests/test_db.py tests/test_pipeline.py tests/test_cli.py -q`
Expected: 與 Step 1 相同的 PASS 數。

- [ ] **Step 7: Commit**

```bash
git add sentinel/persistence.py
git commit -m "perf: vectorize persistence upserts and add date type hints"
```

---

### Task 3: quality.py 價格異常檢測向量化（Phase 2）

**Files:**
- Modify: `sentinel/quality.py:82-149`（`_detect_price_spikes`）
- Test: `tests/test_quality.py`（先加一個鎖行為的回歸測試）

- [ ] **Step 1: 加回歸測試鎖定既有行為**

在 `tests/test_quality.py` 加入：

```python
def test_spike_uses_most_recent_prior_close_within_batch():
    """同批次內跨日比較：第二天的漲幅應以第一天收盤為基準。"""
    import pandas as pd
    from sentinel.quality import validate_daily_prices

    prices = pd.DataFrame(
        [
            {"market": "TWSE", "symbol": "2330", "trading_date": "2026-03-02",
             "open": 100, "high": 101, "low": 99, "close": 100, "volume": 1000, "turnover": 1},
            {"market": "TWSE", "symbol": "2330", "trading_date": "2026-03-03",
             "open": 100, "high": 130, "low": 99, "close": 130, "volume": 1000, "turnover": 1},
            # 另一檔正常股，避免觸發 bulk-anomaly guard（>15% 同日清旗標）
            *[
                {"market": "TWSE", "symbol": f"11{i:02d}", "trading_date": "2026-03-03",
                 "open": 50, "high": 51, "low": 49, "close": 50, "volume": 500, "turnover": 1}
                for i in range(10)
            ],
        ]
    )
    reference = pd.DataFrame(
        [
            {"market": "TWSE", "symbol": f"11{i:02d}", "trading_date": "2026-03-02",
             "open": 50, "high": 51, "low": 49, "close": 50, "volume": 500, "turnover": 1}
            for i in range(10)
        ]
    )
    result = validate_daily_prices(prices, reference_prices=reference)
    flagged = set(result.invalid_prices["symbol"])
    assert "2330" in flagged           # +30% 應被攔下
    assert len(flagged) == 1           # 其餘正常
```

Run: `.venv/bin/python -m pytest tests/test_quality.py -v`
Expected: 新測試 PASS（鎖定現狀），全綠後才動手重構。

- [ ] **Step 2: 重寫 `_detect_price_spikes` 為向量化版本**

```python
def _detect_price_spikes(
    frame: pd.DataFrame,
    reference_prices: pd.DataFrame,
    threshold: float,
) -> pd.Series:
    """Return a bool Series (same index as frame) marking rows whose close
    deviates more than `threshold` from the most recent prior-session close.

    Reference is built from both `reference_prices` (historical CSV) and the
    current `frame` itself so that within-batch cross-day comparisons use the
    same data source.  Rows with no prior close are NOT flagged (safe default).

    Bulk-anomaly guard: if more than 15% of a trading date's rows are flagged,
    the flags for that date are cleared — this indicates a reference data
    failure (e.g. holiday gap, ex-dividend wave) rather than genuine bad data.
    """
    combined_ref = pd.concat([reference_prices, frame], ignore_index=True)
    combined_ref["trading_date"] = pd.to_datetime(combined_ref["trading_date"]).dt.date
    combined_ref = (
        combined_ref.sort_values("trading_date")
        .drop_duplicates(subset=["market", "symbol", "trading_date"], keep="last")
        .sort_values(["market", "symbol", "trading_date"])
    )
    # 每列的「最近前一交易日收盤」＝組內 shift(1)
    combined_ref["prev_close"] = combined_ref.groupby(["market", "symbol"])["close"].shift(1)

    keyed = frame[["market", "symbol", "close"]].copy()
    keyed["trading_date"] = pd.to_datetime(frame["trading_date"]).dt.date
    merged = keyed.merge(
        combined_ref[["market", "symbol", "trading_date", "prev_close"]],
        on=["market", "symbol", "trading_date"],
        how="left",
    )
    merged.index = frame.index

    prev_close = pd.to_numeric(merged["prev_close"], errors="coerce")
    current_close = pd.to_numeric(merged["close"], errors="coerce")
    valid = prev_close.notna() & (prev_close != 0) & current_close.notna()
    change = (current_close - prev_close).abs() / prev_close.abs()
    spike_flags = valid & (change > threshold)

    # Bulk-anomaly guard
    frame_dates = pd.to_datetime(frame["trading_date"]).dt.date
    flag_ratio = spike_flags.groupby(frame_dates).transform("mean")
    spike_flags = spike_flags & ~(flag_ratio > 0.15)

    return spike_flags
```

注意：`frame` 在呼叫端已 `reset_index(drop=True)`，且 (market, symbol, trading_date) 在
`combined_ref` 去重後唯一，merge 不會放大列數。

- [ ] **Step 3: 跑測試確認行為不變**

Run: `.venv/bin/python -m pytest tests/test_quality.py tests/test_pipeline.py -q`
Expected: 全 PASS（含 Step 1 的新測試）。

- [ ] **Step 4: Commit**

```bash
git add sentinel/quality.py tests/test_quality.py
git commit -m "perf: vectorize price spike detection in quality checks"
```

---

### Task 4: intraday/engine.py 魔術數字抽常數（Phase 2）

**Files:**
- Modify: `sentinel/intraday/engine.py`

- [ ] **Step 1: 在 logger 宣告後加入模組常數**

```python
# Tomorrow's Star 策略參數
DEFAULT_TOP_N = 300            # 以昨日成交量取前 N 檔為掃描對象
DEFAULT_MIN_GAIN = 0.075       # 最終漲幅門檻（7.5%）
MAX_PRICE = 1000.0             # 股價上限，排除高價股
INTRADAY_MIN_GAIN = 0.03       # 盤中初步漲幅門檻（3%）
VOLUME_RATIO_MIN = 1.5         # 成交量需達 5 日均量的倍數
GREAT_POWER_LOCK_RATIO = 3.0   # 最後一筆量 ≥ 鎖單量/此值 視為大戶力道
VOLUME_AVG_WINDOW_DAYS = 5     # 均量計算視窗
```

- [ ] **Step 2: 替換引用**

- 簽名改為 `def run_tomorrow_star_scan(session: Session, top_n: int = DEFAULT_TOP_N, min_gain: float = DEFAULT_MIN_GAIN)`（移除行內 `# 7.5%` 註解）
- 126 行 `if p["close"] > 1000:` → `if p["close"] > MAX_PRICE:`
- 130 行 `if gain < 0.03 or ...` → `if gain < INTRADAY_MIN_GAIN or ...`
- 135 行 `avg_v5 * 1.5` → `avg_v5 * VOLUME_RATIO_MIN`
- 81 行 `subq.c.rn <= 5` → `subq.c.rn <= VOLUME_AVG_WINDOW_DAYS`
- 156 行 `locked_vol / 3.0` → `locked_vol / GREAT_POWER_LOCK_RATIO`

- [ ] **Step 3: 跑測試**

Run: `.venv/bin/python -m pytest -q`
Expected: 全 PASS。

- [ ] **Step 4: Commit**

```bash
git add sentinel/intraday/engine.py
git commit -m "refactor: extract tomorrow-star scan thresholds to module constants"
```

---

### Task 5: ui_tasks.json 保留上限（Phase 2）

**Files:**
- Modify: `ui/services/command_runner.py`（`TaskStore`）
- Test: `tests/ui/test_command_runner.py`

- [ ] **Step 1: 寫失敗測試**

在 `tests/ui/test_command_runner.py` 加入：

```python
def test_task_store_prunes_to_max_tasks(tmp_path):
    from ui.services.command_runner import TaskRun, TaskStore, _MAX_TASKS

    store = TaskStore(path=tmp_path / "tasks.json")
    for i in range(_MAX_TASKS + 50):
        store.save(
            TaskRun(
                task_id=f"t{i:04d}",
                command_id="run",
                argv=["echo"],
                status="success",
                started_at=f"2026-06-10T00:{i // 60:02d}:{i % 60:02d}",
            )
        )

    tasks = store.list_all()
    assert len(tasks) == _MAX_TASKS
    # 留下的必須是最新的一批
    assert tasks[0].task_id == f"t{_MAX_TASKS + 49:04d}"


def test_task_store_never_prunes_running_tasks(tmp_path):
    from ui.services.command_runner import TaskRun, TaskStore, _MAX_TASKS

    store = TaskStore(path=tmp_path / "tasks.json")
    store.save(
        TaskRun(task_id="running-old", command_id="run", argv=["echo"],
                status="running", started_at="2020-01-01T00:00:00")
    )
    for i in range(_MAX_TASKS + 10):
        store.save(
            TaskRun(
                task_id=f"t{i:04d}",
                command_id="run",
                argv=["echo"],
                status="success",
                started_at=f"2026-06-10T00:{i // 60:02d}:{i % 60:02d}",
            )
        )

    ids = {t.task_id for t in store.list_all()}
    assert "running-old" in ids
```

Run: `.venv/bin/python -m pytest tests/ui/test_command_runner.py -v`
Expected: ImportError（`_MAX_TASKS` 不存在）→ FAIL。

- [ ] **Step 2: 實作修剪邏輯**

`ui/services/command_runner.py` 在 `_LOG_TAIL_LINES = 100` 後加：

```python
_MAX_TASKS = 200
```

`TaskStore._save_all` 改為：

```python
    def _save_all(self, data: dict[str, dict]) -> None:
        if len(data) > _MAX_TASKS:
            ordered = sorted(
                data.values(), key=lambda d: d.get("started_at") or "", reverse=True
            )
            kept = ordered[:_MAX_TASKS]
            running_overflow = [
                d for d in ordered[_MAX_TASKS:] if d.get("status") == "running"
            ]
            data = {d["task_id"]: d for d in kept + running_overflow}
        self._path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
```

- [ ] **Step 3: 跑測試確認通過**

Run: `.venv/bin/python -m pytest tests/ui/ -q`
Expected: 全 PASS。

- [ ] **Step 4: Commit**

```bash
git add ui/services/command_runner.py tests/ui/test_command_runner.py
git commit -m "feat(ui): cap ui_tasks.json at 200 entries with running-task protection"
```

---

### Task 6: 拆分 indicators.py 的 `_compute_group_indicators`（Phase 2）

**Files:**
- Modify: `sentinel/indicators.py:216-500`

行為完全不變的搬移式重構：把 285 行的函式按主題拆成六個模組層級私有函式，
每個函式接收 `group` 與已轉好型別的價格 Series，**原地**對 `group` 加欄位
（與現行為一致）。主函式變成編排器。

- [ ] **Step 1: 跑基準測試**

Run: `.venv/bin/python -m pytest tests/test_pipeline.py tests/test_cli.py -q`
Expected: 全 PASS（記下數量）。

- [ ] **Step 2: 重構**

新結構（所有程式碼內容自既有 216-500 行**逐字搬移**，僅換縮排歸屬；
括號內為來源行範圍）：

```python
def _resolve_price_series(group: pd.DataFrame) -> Dict[str, pd.Series]:
    """還原調整後 OHLC 與原始收盤（來源：217-238 行）。
    回傳 {"close", "open_p", "high", "low", "raw_close", "volume"}。"""


def _add_moving_average_indicators(group: pd.DataFrame, close: pd.Series, volume: pd.Series) -> None:
    """均線、均線方向、量均（來源：240-248 行）。"""


def _add_oscillator_indicators(
    group: pd.DataFrame, close: pd.Series, open_p: pd.Series, high: pd.Series, low: pd.Series
) -> None:
    """RSI、MACD、KD、ATR、布林、high_20、紅K、日內位置、漲跌幅
    （來源：249-272 行）。"""


def _add_purity_and_blackcandle_indicators(
    group: pd.DataFrame, close: pd.Series, open_p: pd.Series, high: pd.Series
) -> None:
    """is_pure_stock 判定與黑K多週期欄位（來源：274-325 行，含 open_47d_prev/high_47d_prev）。"""


def _add_washout_recovery_indicators(
    group: pd.DataFrame, close: pd.Series, high: pd.Series, low: pd.Series, volume: pd.Series
) -> None:
    """47D 洗盤回升、ma10/ma20/ma30 站回系列、is_stuck_data
    （來源：327-407 行）。"""


def _add_multi_period_and_pattern_indicators(
    group: pd.DataFrame,
    close: pd.Series,
    open_p: pd.Series,
    high: pd.Series,
    low: pd.Series,
    raw_close: pd.Series,
    volume: pd.Series,
) -> None:
    """3D 突破輔助欄、47D/18D 參考點、raw 系列、影線/K棒型態、前日量
    （來源：409-498 行）。"""


def _compute_group_indicators(group: pd.DataFrame) -> pd.DataFrame:
    series = _resolve_price_series(group)
    close, open_p, high, low = series["close"], series["open_p"], series["high"], series["low"]
    raw_close, volume = series["raw_close"], series["volume"]

    _add_moving_average_indicators(group, close, volume)
    _add_oscillator_indicators(group, close, open_p, high, low)
    _add_purity_and_blackcandle_indicators(group, close, open_p, high)
    _add_washout_recovery_indicators(group, close, high, low, volume)
    _add_multi_period_and_pattern_indicators(group, close, open_p, high, low, raw_close, volume)
    return group
```

搬移注意事項：
- `_resolve_price_series` 回傳 dict，結尾為：
  ```python
  return {"close": close, "open_p": open_p, "high": high, "low": low,
          "raw_close": raw_close, "volume": volume}
  ```
- 347-348 行的 `cp_close = close.shift(1)`、`cp_ma20 = group["ma20"].shift(1)` 與
  394-396 行的 `group["prev_close"] = cp_close`、`group["prev_ma20"] = cp_ma20`
  同屬 `_add_washout_recovery_indicators`，一起搬。
- 函式必須維持模組層級（ProcessPoolExecutor pickling 需求）。
- 不改任何運算式，只搬移與重新縮排。

- [ ] **Step 3: 數值回歸驗證（除測試外的快速煙霧測試）**

```bash
.venv/bin/python - <<'EOF'
import pandas as pd
from sentinel.indicators import compute_indicator_frame

rows = []
for i in range(250):
    rows.append({"market": "TWSE", "symbol": "2330",
                 "trading_date": pd.Timestamp("2025-06-01") + pd.Timedelta(days=i),
                 "open": 100 + i * 0.1, "high": 101 + i * 0.1, "low": 99 + i * 0.1,
                 "close": 100.5 + i * 0.1, "volume": 1000 + i, "turnover": 1,
                 "name": "台積電", "adjusted_close": 100.5 + i * 0.1})
frame = compute_indicator_frame(pd.DataFrame(rows))
print(frame[["ma20", "rsi14", "macd_line", "kd_k", "is_pure_stock"]].tail(3))
EOF
```
Expected: 正常輸出數值、無例外。

- [ ] **Step 4: 跑基準測試**

Run: `.venv/bin/python -m pytest tests/test_pipeline.py tests/test_cli.py -q` 之後全套 `pytest -q`
Expected: 與 Step 1 相同 PASS 數。

- [ ] **Step 5: Commit**

```bash
git add sentinel/indicators.py
git commit -m "refactor: split _compute_group_indicators into focused helper functions"
```

---

## 完成定義

- 全套 pytest 通過、`make check` 乾淨。
- 六個 commit 依序落地。
- 完成後回報，再進入 Phase 3 計畫（TPEX 解析器、網路抓取、Scheduler 接線、分鐘級回測 CLI）。
