"""Sentinel UI — Overview 頁面（首頁）。"""

from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))

from datetime import date, timedelta
from typing import Optional

import pandas as pd
import streamlit as st

from ui.components.layout import inject_css, section_header
from ui.services.command_runner import find_running_task, get_store, launch_task, poll_all_running
from ui.services.command_specs import RUN, RUN_INTRADAY, SYNC
from ui.services.db import get_engine
from ui.services.docker_service import get_db_container_status, start_db_container
from ui.services.queries import (
    get_data_freshness,
    get_latest_job_runs,
    get_latest_price_date,
    get_latest_scan_summary,
)


@st.cache_data(ttl=300, show_spinner=False)
def _cached_latest_price_date():
    try:
        return get_latest_price_date(get_engine())
    except Exception:
        return None


@st.cache_data(ttl=60, show_spinner=False)
def _cached_scan_summary() -> dict:
    return get_latest_scan_summary(get_engine())


@st.cache_data(ttl=120, show_spinner=False)
def _cached_data_freshness():
    return get_data_freshness(get_engine())


@st.cache_data(ttl=30, show_spinner=False)
def _cached_job_runs(limit: int = 10):
    return get_latest_job_runs(get_engine(), limit=limit)

st.set_page_config(
    page_title="Sentinel 選股系統",
    page_icon="📡",
    layout="wide",
    initial_sidebar_state="expanded",
)
inject_css()

st.title("📡 Sentinel 選股系統")
st.caption("台股篩選 / 回測 / 盤中監控儀表板")

store = get_store()

# ── 最新收盤日（供快速 Run 使用）────────────────────────────────────────────
_latest_price_date: Optional[date] = None
try:
    _latest_price_date = _cached_latest_price_date()
except Exception:
    pass


# ── 執行中任務自動輪詢（fragment 獨立刷新，不重跑整頁）───────────────────
@st.fragment(run_every=5)
def _running_banner() -> None:
    poll_all_running()
    running = store.list_by_status("running")
    if running:
        names = ", ".join(t.command_id for t in running[:3])
        st.warning(f"⚙️ {len(running)} 個任務執行中：{names}　→　[Task Center](/9_Task_Center)")


_running_banner()

# ── 快速操作 ────────────────────────────────────────────────────────────────
section_header("快速操作", "一鍵啟動常用任務（長任務在 Task Center 追蹤）")
qa1, qa2, qa3, qa4, qa5 = st.columns(5)

if qa1.button("▶ Sync（TWSE + TPEX）", width='stretch'):
    _running_sync = find_running_task(SYNC.command_id)
    if _running_sync:
        st.warning(
            f"⚠️ sync 任務已在執行中（#{_running_sync.task_id}）→ [Task Center](/9_Task_Center)"
        )
    else:
        task = launch_task(SYNC, {"market": ["TWSE", "TPEX"]})
        st.session_state["_last_sync_task"] = task.task_id
        st.rerun()

if qa2.button("▶ Run（最新收盤日）", width='stretch'):
    _running_run = find_running_task(RUN.command_id)
    if _running_run:
        st.warning(
            f"⚠️ run 任務已在執行中（#{_running_run.task_id}）→ [Task Center](/9_Task_Center)"
        )
    else:
        _run_date = _latest_price_date or date.today()
        task = launch_task(
            RUN,
            {
                "start-date": (_run_date - timedelta(days=1)).isoformat(),
                "end-date": _run_date.isoformat(),
                "market": ["TWSE", "TPEX"],
            },
        )
        st.session_state["_last_run_task"] = task.task_id
        st.rerun()

if qa3.button("▶ Run Intraday", width='stretch'):
    _running_intraday = find_running_task(RUN_INTRADAY.command_id)
    if _running_intraday:
        st.warning(
            f"⚠️ run-intraday 任務已在執行中（#{_running_intraday.task_id}）→ [Task Center](/9_Task_Center)"
        )
    else:
        task = launch_task(RUN_INTRADAY, {"top": 300, "min-gain": 0.075})
        st.session_state["_last_intraday_task"] = task.task_id
        st.rerun()

if qa4.button("🔄 清除快取並刷新", width='stretch'):
    st.cache_resource.clear()
    st.rerun()

if qa5.button("📥 每日盤後", width='stretch'):
    st.switch_page("pages/12_Daily_Fetch.py")

# ── 快速操作後 CTA ──────────────────────────────────────────────────────────
if st.session_state.get("_last_sync_task"):
    st.success(f"已送出 sync 任務 #{st.session_state['_last_sync_task']}")
    st.info("完成後可至首頁查看資料新鮮度")
if st.session_state.get("_last_run_task"):
    st.success(f"已送出 run 任務 #{st.session_state['_last_run_task']}")
    st.page_link("pages/3_Daily_Scan.py", label="→ 前往 Daily Scan 查看結果", icon="📊")
if st.session_state.get("_last_intraday_task"):
    st.success(f"已送出 run-intraday 任務 #{st.session_state['_last_intraday_task']}")
    st.page_link("pages/6_Intraday.py", label="→ 前往 Intraday 查看", icon="⚡")

st.divider()


# ── 資料庫狀態 ──────────────────────────────────────────────────────────────
@st.cache_data(ttl=10, show_spinner=False)
def _cached_db_status() -> str:
    return get_db_container_status()


section_header("資料庫狀態", "Docker 容器監控（重開機後需手動啟動）")
_db_status = _cached_db_status()

_status_col, _action_col = st.columns([4, 1])
with _status_col:
    if _db_status == "running":
        st.success("✅ PostgreSQL / TimescaleDB 容器運行中")
    elif _db_status == "stopped":
        st.error("❌ DB 容器未啟動，請點擊右側「啟動 DB」按鈕")
    else:
        st.warning("⚠️ Docker 不可用，請確認 Docker Desktop 已啟動後再試")

with _action_col:
    st.write("")
    if _db_status == "stopped":
        if st.button("▶ 啟動 DB", width='stretch', type="primary"):
            with st.spinner("正在啟動 DB 容器..."):
                _ok, _msg = start_db_container()
            if _ok:
                st.success(_msg)
                st.cache_data.clear()
                st.cache_resource.clear()
                st.rerun()
            else:
                st.error(f"啟動失敗：{_msg}")
    elif _db_status == "running":
        if st.button("🔄 重新檢查", width='stretch'):
            st.cache_data.clear()
            st.cache_resource.clear()
            st.rerun()

st.divider()

# ── 資料庫連線 ──────────────────────────────────────────────────────────────
try:
    engine = get_engine()
except Exception as e:
    if _db_status == "stopped":
        st.error("DB 容器尚未啟動，請使用上方「啟動 DB」按鈕")
    elif _db_status == "docker_unavailable":
        st.error("Docker 未啟動，請先開啟 Docker Desktop 再試")
    else:
        st.error(f"資料庫連線失敗：{e}")
        st.info("請確認 .env 已設定 TS_DATABASE_URL")
    st.stop()

# ── 資料新鮮度 KPI ──────────────────────────────────────────────────────────
section_header("資料新鮮度")
scan_summary = _cached_scan_summary()
freshness_df = _cached_data_freshness()

m1, m2, m3, m4 = st.columns(4)
m1.metric("最新掃描日期", str(scan_summary["latest_date"]) if scan_summary["latest_date"] else "—")
m2.metric("當日命中股數", scan_summary["total_hits"])

if not freshness_df.empty:
    price_map = freshness_df.set_index("market")["latest_date"].to_dict()
    symbol_map = freshness_df.set_index("market")["symbol_count"].to_dict()
    m3.metric("TWSE 最新日", str(price_map.get("TWSE", "—")))
    m4.metric("TPEX 最新日", str(price_map.get("TPEX", "—")))

# ── 策略命中摘要 ────────────────────────────────────────────────────────────
section_header(
    "策略命中摘要",
    (
        f"掃描日：{scan_summary['latest_date']} ｜ 總命中：{scan_summary['total_hits']} 檔"
        if scan_summary["latest_date"]
        else "尚無掃描資料"
    ),
)
by_strategy = scan_summary.get("by_strategy")
if by_strategy is not None and not by_strategy.empty:
    col_chart, col_table = st.columns([3, 1])
    with col_chart:
        st.bar_chart(by_strategy.set_index("strategy_id")["hits"], color="#3D6E8F")
    with col_table:
        st.dataframe(by_strategy, width="stretch", hide_index=True)
    st.page_link("pages/3_Daily_Scan.py", label="查看完整結果 →", icon="📊")
else:
    st.info("尚無掃描結果，請前往 Daily Scan 執行 Pipeline")
    st.page_link("pages/3_Daily_Scan.py", label="前往 Daily Scan 執行 →", icon="📊")

st.divider()

# ── 最近 UI 任務 ────────────────────────────────────────────────────────────
section_header("最近 UI 任務（Top 10）")
all_tasks = store.list_all()[:10]
if all_tasks:
    rows = [
        {
            "狀態": t.status.upper(),
            "指令": t.command_id,
            "Task ID": t.task_id,
            "開始時間": t.started_at[:19] if t.started_at else "—",
            "耗時": t.duration_str,
            "Exit": str(t.exit_code) if t.exit_code is not None else "—",
        }
        for t in all_tasks
    ]
    st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)
else:
    st.info("尚無任務記錄")

st.divider()

# ── DB JobRun ───────────────────────────────────────────────────────────────
section_header("DB Job 記錄（sentinel 內建 pipeline）")
job_df = _cached_job_runs(limit=10)
if not job_df.empty:
    from ui.components.tables import render_job_runs

    render_job_runs(job_df)
else:
    st.info("尚無 DB Job 記錄")

# ── 資料完整度 ──────────────────────────────────────────────────────────────
if not freshness_df.empty:
    section_header("各市場資料完整度")
    st.dataframe(freshness_df, width="stretch", hide_index=True)
