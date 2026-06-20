# Daily Fetch 每日盤後資料 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a dedicated 📥 每日盤後 page that lets the user sync today's price data, institutional flows, and main-force data (watchlist batch + single symbol) with idempotency guards that prevent re-fetching already-synced data.

**Architecture:** New page `ui/pages/12_Daily_Fetch.py` holds all UI. Two new pure-query functions in `ui/services/queries.py` provide freshness data. Home page gets a 5th quick-action button that navigates to the new page. No new CLI commands or backend models are needed.

**Tech Stack:** Python 3.11, Streamlit 1.50, SQLAlchemy 2, pytest with in-memory SQLite.

## Global Constraints

- All Streamlit buttons use `width='stretch'` (not `use_container_width=True` — deprecated in 1.50)
- Watchlist file: `data/ui_watchlist.json`, format `[{"symbol": "2330", "name": "台積電"}, ...]`
- Tests use in-memory SQLite: `create_db_engine("sqlite://")` + `create_schema(eng)`
- `MainForceDaily` inserts require `top_n` field (e.g. `top_n=15`)
- Freshness: today == `date.today()` in production code (not hardcoded)
- Task store fallback key: look for `status == "success"` + matching `command_id` with `started_at` starting with today's ISO date prefix (`YYYY-MM-DD`)

---

## File Map

| Action | Path | Responsibility |
|---|---|---|
| Modify | `ui/services/queries.py` | Add `get_latest_institutional_date`, `get_latest_main_force_dates` |
| Create | `tests/ui/test_queries_daily_fetch.py` | Unit tests for the two new query functions |
| Create | `ui/pages/12_Daily_Fetch.py` | New page: 3 sections, freshness badges, launch buttons |
| Modify | `ui/app.py` | 4 → 5 quick-action columns; add 📥 navigation button |

---

## Task 1: Add freshness queries to `ui/services/queries.py`

**Files:**
- Modify: `ui/services/queries.py` (append after `get_latest_scan_summary`)
- Create: `tests/ui/test_queries_daily_fetch.py`

**Interfaces:**
- Produces:
  - `get_latest_institutional_date(engine: Engine) -> date | None`
  - `get_latest_main_force_dates(engine: Engine, symbols: list[str]) -> dict[str, date | None]`

- [ ] **Step 1: Write failing tests**

Create `tests/ui/test_queries_daily_fetch.py`:

```python
"""Tests for freshness queries used by the 每日盤後 page."""

from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from sentinel.db import create_db_engine, create_schema
from sentinel.models import InstitutionalFlow, MainForceDaily
from ui.services.queries import (
    get_latest_institutional_date,
    get_latest_main_force_dates,
)


@pytest.fixture()
def engine() -> Engine:
    eng = create_db_engine("sqlite://")
    create_schema(eng)
    return eng


# ── get_latest_institutional_date ─────────────────────────────────────────


def test_get_latest_institutional_date_returns_max(engine: Engine) -> None:
    """Returns the highest trading_date across all markets/symbols."""
    with Session(engine) as s:
        s.add(InstitutionalFlow(
            market="TWSE", symbol="2330", trading_date=date(2026, 6, 18),
            foreign_net=1000, investment_trust_net=0, dealer_net=0, total_net=1000,
        ))
        s.add(InstitutionalFlow(
            market="TPEX", symbol="5483", trading_date=date(2026, 6, 20),
            foreign_net=500, investment_trust_net=0, dealer_net=0, total_net=500,
        ))
        s.commit()

    result = get_latest_institutional_date(engine)

    assert result == date(2026, 6, 20)


def test_get_latest_institutional_date_empty_returns_none(engine: Engine) -> None:
    """Returns None when the table is empty."""
    assert get_latest_institutional_date(engine) is None


# ── get_latest_main_force_dates ───────────────────────────────────────────


def test_get_latest_main_force_dates_returns_per_symbol(engine: Engine) -> None:
    """Returns the max trading_date for each requested symbol."""
    with Session(engine) as s:
        for d in [date(2026, 6, 18), date(2026, 6, 20)]:
            s.add(MainForceDaily(
                market="TWSE", symbol="2330", trading_date=d,
                main_buy=10000, main_sell=-5000, main_net=5000, top_n=15,
            ))
        s.add(MainForceDaily(
            market="TPEX", symbol="5347", trading_date=date(2026, 6, 19),
            main_buy=3000, main_sell=-1000, main_net=2000, top_n=15,
        ))
        s.commit()

    result = get_latest_main_force_dates(engine, ["2330", "5347"])

    assert result["2330"] == date(2026, 6, 20)
    assert result["5347"] == date(2026, 6, 19)


def test_get_latest_main_force_dates_missing_symbol_returns_none(engine: Engine) -> None:
    """Symbols with no data in the table map to None."""
    result = get_latest_main_force_dates(engine, ["9999", "1234"])

    assert result == {"9999": None, "1234": None}


def test_get_latest_main_force_dates_empty_symbols(engine: Engine) -> None:
    """Empty symbols list returns empty dict without querying."""
    assert get_latest_main_force_dates(engine, []) == {}
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
.venv/bin/pytest tests/ui/test_queries_daily_fetch.py -v
```

Expected: `ImportError` — `get_latest_institutional_date` and `get_latest_main_force_dates` not defined yet.

- [ ] **Step 3: Add the two functions to `ui/services/queries.py`**

Append after the last function in the file (`get_latest_scan_summary`):

```python
def get_latest_institutional_date(engine: Engine) -> Optional[date]:
    """查詢 InstitutionalFlow 最新 trading_date；無資料時回傳 None。"""
    with Session(engine) as s:
        return s.query(func.max(InstitutionalFlow.trading_date)).scalar()


def get_latest_main_force_dates(
    engine: Engine, symbols: list[str]
) -> dict[str, Optional[date]]:
    """批次查詢各個股 MainForceDaily 最新 trading_date。

    回傳 {symbol: date | None}，清單中但 DB 無資料的個股映射到 None。
    """
    if not symbols:
        return {}
    with Session(engine) as s:
        rows = (
            s.query(MainForceDaily.symbol, func.max(MainForceDaily.trading_date))
            .filter(MainForceDaily.symbol.in_(symbols))
            .group_by(MainForceDaily.symbol)
            .all()
        )
    result: dict[str, Optional[date]] = {sym: None for sym in symbols}
    for sym, d in rows:
        result[sym] = d
    return result
```

- [ ] **Step 4: Run tests again — all should pass**

```bash
.venv/bin/pytest tests/ui/test_queries_daily_fetch.py -v
```

Expected: 5 tests PASSED.

- [ ] **Step 5: Commit**

```bash
git add ui/services/queries.py tests/ui/test_queries_daily_fetch.py
git commit -m "feat: add get_latest_institutional_date and get_latest_main_force_dates queries"
```

---

## Task 2: Create `ui/pages/12_Daily_Fetch.py`

**Files:**
- Create: `ui/pages/12_Daily_Fetch.py`

**Interfaces:**
- Consumes (from Task 1):
  - `get_latest_institutional_date(engine: Engine) -> date | None`
  - `get_latest_main_force_dates(engine: Engine, symbols: list[str]) -> dict[str, date | None]`
- Consumes (existing):
  - `get_data_freshness(engine)` → `pd.DataFrame` with columns `market`, `latest_date`, `symbol_count`
  - `launch_task(spec, params)` → `TaskRun`
  - `find_running_task(command_id)` → `TaskRun | None`
  - `poll_all_running()` → `list[TaskRun]`
  - `get_store()` → `TaskStore` (for task-store fallback)
  - Specs: `SYNC`, `SYNC_INSTITUTIONAL`, `SYNC_MAIN_FORCE`

- [ ] **Step 1: Create the page file**

Create `ui/pages/12_Daily_Fetch.py`:

```python
"""每日盤後資料 — 一鍵同步今日股價、法人買賣超、主力分點。"""

from __future__ import annotations

import json
import pathlib
import sys
from datetime import date

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent.parent))

import streamlit as st

from ui.components.layout import inject_css, section_header
from ui.components.log_viewer import render_log_tail
from ui.services.command_runner import (
    find_running_task,
    get_store,
    launch_task,
    poll_all_running,
    poll_task,
)
from ui.services.command_specs import SYNC, SYNC_INSTITUTIONAL, SYNC_MAIN_FORCE
from ui.services.db import get_engine
from ui.services.queries import (
    get_data_freshness,
    get_latest_institutional_date,
    get_latest_main_force_dates,
)

st.set_page_config(page_title="每日盤後 | Sentinel", layout="wide")
inject_css()
st.title("📥 每日盤後資料")
st.caption("同步今日收盤後的股價、三大法人買賣超、主力分點資料")

_WATCHLIST_PATH = pathlib.Path(__file__).parent.parent.parent / "data" / "ui_watchlist.json"
_today = date.today()

poll_all_running()
store = get_store()

# ── 取得 DB engine（可能失敗）─────────────────────────────────────────────
_engine = None
try:
    _engine = get_engine()
except Exception:
    st.warning("⚠️ 資料庫連線失敗，防呆機制改用任務記錄判斷")


def _task_store_synced_today(command_id: str) -> bool:
    """Fallback: check task store for a successful run of command_id today."""
    today_prefix = _today.isoformat()
    for t in store.list_all():
        if (
            t.command_id == command_id
            and t.status == "success"
            and (t.started_at or "").startswith(today_prefix)
        ):
            return True
    return False


def _is_price_synced() -> bool:
    if _engine is not None:
        try:
            df = get_data_freshness(_engine)
            if df.empty:
                return False
            dates = df.set_index("market")["latest_date"].to_dict()
            return dates.get("TWSE") == _today and dates.get("TPEX") == _today
        except Exception:
            pass
    return _task_store_synced_today("sync")


def _is_institutional_synced() -> bool:
    if _engine is not None:
        try:
            latest = get_latest_institutional_date(_engine)
            return latest == _today
        except Exception:
            pass
    return _task_store_synced_today("sync-institutional")


def _load_watchlist() -> list[dict]:
    if not _WATCHLIST_PATH.exists():
        return []
    try:
        return json.loads(_WATCHLIST_PATH.read_text(encoding="utf-8"))
    except Exception:
        return []


def _get_main_force_dates(symbols: list[str]) -> dict[str, date | None]:
    if _engine is not None and symbols:
        try:
            return get_latest_main_force_dates(_engine, symbols)
        except Exception:
            pass
    return {sym: None for sym in symbols}


def _show_task_result(task_id: str) -> None:
    task = poll_task(task_id)
    if task.status == "success":
        st.success(f"✅ 完成（耗時 {task.duration_str}）")
    elif task.status == "failed":
        st.error(f"❌ 失敗（耗時 {task.duration_str}）")
    if task.stdout_tail or task.stderr_tail:
        render_log_tail(task.stdout_tail, task.stderr_tail)


# ═══════════════════════════════════════════════════════════════════════════
# Section 1: 今日股價同步
# ═══════════════════════════════════════════════════════════════════════════

section_header("今日股價同步", "sync — 自動補齊 TWSE + TPEX 至今日")

_price_synced = _is_price_synced()
if _price_synced:
    st.success(f"✅ 今日股價已同步（{_today}）")

_price_running = find_running_task(SYNC.command_id)
_price_btn_label = "重新同步" if _price_synced else "▶ 同步今日股價"

if _price_running:
    st.info(f"⚙️ 同步中（#{_price_running.task_id}）→ [Task Center](/9_Task_Center)")
elif st.button(_price_btn_label, key="btn_price_sync", disabled=False, width='stretch'):
    task = launch_task(SYNC, {"market": ["TWSE", "TPEX"]})
    st.session_state["_df_price_task"] = task.task_id
    st.rerun()

if st.session_state.get("_df_price_task"):
    _show_task_result(st.session_state["_df_price_task"])

st.divider()

# ═══════════════════════════════════════════════════════════════════════════
# Section 2: 三大法人買賣超
# ═══════════════════════════════════════════════════════════════════════════

section_header("三大法人買賣超", "sync-institutional — 今日三大法人進出明細")

_inst_synced = _is_institutional_synced()
if _inst_synced:
    st.success(f"✅ 今日法人資料已同步（{_today}）")

_inst_running = find_running_task(SYNC_INSTITUTIONAL.command_id)
_inst_btn_label = "重新同步" if _inst_synced else "▶ 同步今日法人資料"

if _inst_running:
    st.info(f"⚙️ 同步中（#{_inst_running.task_id}）→ [Task Center](/9_Task_Center)")
elif st.button(_inst_btn_label, key="btn_inst_sync", width='stretch'):
    task = launch_task(SYNC_INSTITUTIONAL, {"date": _today.isoformat()})
    st.session_state["_df_inst_task"] = task.task_id
    st.rerun()

if st.session_state.get("_df_inst_task"):
    _show_task_result(st.session_state["_df_inst_task"])

st.divider()

# ═══════════════════════════════════════════════════════════════════════════
# Section 3: 主力分點同步
# ═══════════════════════════════════════════════════════════════════════════

section_header("主力分點同步", "sync-main-force — 依關注清單或單一個股")

tab_batch, tab_single = st.tabs(["批次（關注清單）", "單一臨時"])

# ── Tab A: 批次 ───────────────────────────────────────────────────────────
with tab_batch:
    watchlist = _load_watchlist()

    if not watchlist:
        st.info("關注清單為空，請先至「個股訊號檢驗」頁面加入關注股票。")
        st.page_link("pages/4_Stock_Check.py", label="→ 前往個股訊號檢驗", icon="🔍")
    else:
        symbols = [item["symbol"] for item in watchlist]
        mf_dates = _get_main_force_dates(symbols)

        st.markdown("勾選要同步的個股（已同步今日者預設不勾）：")

        selected_symbols: list[str] = []
        header_cols = st.columns([0.5, 1.5, 3, 2, 2])
        header_cols[0].markdown("**同步**")
        header_cols[1].markdown("**代號**")
        header_cols[2].markdown("**名稱**")
        header_cols[3].markdown("**最新主力資料**")
        header_cols[4].markdown("**狀態**")

        for item in watchlist:
            sym = item["symbol"]
            name = item.get("name", "")
            latest = mf_dates.get(sym)
            already_synced = latest == _today
            default_checked = not already_synced

            row = st.columns([0.5, 1.5, 3, 2, 2])
            checked = row[0].checkbox(
                "", value=default_checked, key=f"mf_chk_{sym}", label_visibility="collapsed"
            )
            row[1].write(sym)
            row[2].write(name)
            row[3].write(str(latest) if latest else "—")
            row[4].write("✅ 今日已同步" if already_synced else "⬜ 未同步")
            if checked:
                selected_symbols.append(sym)

        st.write("")
        if st.button(
            f"▶ 批次同步（{len(selected_symbols)} 檔）",
            key="btn_mf_batch",
            disabled=len(selected_symbols) == 0,
            width='stretch',
        ):
            launched = 0
            for sym in selected_symbols:
                if find_running_task(SYNC_MAIN_FORCE.command_id) is None:
                    launch_task(
                        SYNC_MAIN_FORCE,
                        {
                            "symbol": sym,
                            "start-date": _today.isoformat(),
                            "end-date": _today.isoformat(),
                        },
                    )
                    launched += 1
            st.success(f"已送出 {launched} 個主力分點同步任務，請至 [Task Center](/9_Task_Center) 追蹤")
            st.rerun()

# ── Tab B: 單一臨時 ───────────────────────────────────────────────────────
with tab_single:
    st.markdown("輸入任一股票代號，立即同步指定日期區間的主力分點資料。")

    col_sym, col_start, col_end = st.columns(3)
    _single_sym = col_sym.text_input("股票代號 *", placeholder="例：2330", key="mf_single_sym")
    _single_start = col_start.date_input("開始日期 *", value=_today, key="mf_single_start")
    _single_end = col_end.date_input("結束日期 *", value=_today, key="mf_single_end")

    if st.button("▶ 同步", key="btn_mf_single", width='stretch'):
        if not _single_sym:
            st.error("請輸入股票代號")
        elif _single_start > _single_end:
            st.error("開始日期不可晚於結束日期")
        else:
            task = launch_task(
                SYNC_MAIN_FORCE,
                {
                    "symbol": _single_sym.strip(),
                    "start-date": _single_start.isoformat(),
                    "end-date": _single_end.isoformat(),
                },
            )
            st.session_state["_df_mf_single_task"] = task.task_id
            st.rerun()

    if st.session_state.get("_df_mf_single_task"):
        _show_task_result(st.session_state["_df_mf_single_task"])
```

- [ ] **Step 2: Smoke-test the new page by starting the dev server and navigating to it**

```bash
.venv/bin/streamlit run ui/app.py &
# Open http://localhost:8501/Daily_Fetch in browser
# Verify: page loads, three sections visible, tabs work, no console errors
# Then kill the server
kill %1
```

- [ ] **Step 3: Commit**

```bash
git add ui/pages/12_Daily_Fetch.py
git commit -m "feat: add 每日盤後 page with price/institutional/main-force sync and freshness guards"
```

---

## Task 3: Add quick-action button on home page

**Files:**
- Modify: `ui/app.py:86` — change `st.columns(4)` to `st.columns(5)` and add 5th button

**Interfaces:**
- Consumes: `st.switch_page` (Streamlit 1.50+)

- [ ] **Step 1: Update the columns and add the navigation button**

In `ui/app.py`, find:

```python
qa1, qa2, qa3, qa4 = st.columns(4)
```

Replace with:

```python
qa1, qa2, qa3, qa4, qa5 = st.columns(5)
```

Then find the block starting with `if qa4.button("🔄 清除快取並刷新"` and add after it:

```python
if qa5.button("📥 每日盤後", width='stretch'):
    st.switch_page("pages/12_Daily_Fetch.py")
```

- [ ] **Step 2: Smoke-test home page**

```bash
.venv/bin/streamlit run ui/app.py &
# Open http://localhost:8501 in browser
# Verify: 5 buttons visible in quick-actions row, clicking 📥 navigates to Daily Fetch page
kill %1
```

- [ ] **Step 3: Commit**

```bash
git add ui/app.py
git commit -m "feat: add 📥 每日盤後 quick-action button on home page"
```

---

## Self-Review

### Spec coverage

| Spec requirement | Task |
|---|---|
| 新頁面 `12_Daily_Fetch.py` | Task 2 |
| Section 1: 今日股價同步 (`sync`) | Task 2 |
| Section 2: 三大法人買賣超 (`sync-institutional`) | Task 2 |
| Section 3 Tab A: 批次關注清單 | Task 2 |
| Section 3 Tab B: 單一臨時 | Task 2 |
| 防呆: DB freshness check (primary) | Task 1 + Task 2 |
| 防呆: task store fallback | Task 2 |
| 防呆: 今日已同步顯示 ✅，按鈕改「重新同步」 | Task 2 |
| 批次：已同步個股預設不勾 | Task 2 |
| 首頁快捷操作新增按鈕 | Task 3 |
| `get_latest_institutional_date` query | Task 1 |
| `get_latest_main_force_dates` query | Task 1 |

All spec requirements covered. ✅

### Placeholder scan

No TBD, TODO, or vague steps found.

### Type consistency

- `get_latest_institutional_date` returns `Optional[date]` — used as `latest == _today` (correct, `date == date`)
- `get_latest_main_force_dates` returns `dict[str, Optional[date]]` — used as `mf_dates.get(sym)` → `latest == _today` (correct, `None == date` is False)
- `launch_task(SYNC_MAIN_FORCE, {"symbol": sym, "start-date": ..., "end-date": ...})` matches `SYNC_MAIN_FORCE` required fields ✅
- `launch_task(SYNC_INSTITUTIONAL, {"date": _today.isoformat()})` — `SYNC_INSTITUTIONAL` has `date` as required field ✅
