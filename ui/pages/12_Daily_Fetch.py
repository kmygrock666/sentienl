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
    elif task.status == "running":
        st.info("⚙️ 執行中…")
    if task.status in ("success", "failed") and (task.stdout_tail or task.stderr_tail):
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
elif st.button(_price_btn_label, key="btn_price_sync", width="stretch"):
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
elif st.button(_inst_btn_label, key="btn_inst_sync", width="stretch"):
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
            width="stretch",
        ):
            for sym in selected_symbols:
                launch_task(
                    SYNC_MAIN_FORCE,
                    {
                        "symbol": sym,
                        "start-date": _today.isoformat(),
                        "end-date": _today.isoformat(),
                    },
                )
            st.success(
                f"已送出 {len(selected_symbols)} 個主力分點同步任務，請至 [Task Center](/9_Task_Center) 追蹤"
            )
            st.rerun()

# ── Tab B: 單一臨時 ───────────────────────────────────────────────────────
with tab_single:
    st.markdown("輸入任一股票代號，立即同步指定日期區間的主力分點資料。")

    col_sym, col_start, col_end = st.columns(3)
    _single_sym = col_sym.text_input("股票代號 *", placeholder="例：2330", key="mf_single_sym")
    _single_start = col_start.date_input("開始日期 *", value=_today, key="mf_single_start")
    _single_end = col_end.date_input("結束日期 *", value=_today, key="mf_single_end")

    if st.button("▶ 同步", key="btn_mf_single", width="stretch"):
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
