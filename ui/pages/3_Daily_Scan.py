"""Daily Scan — 日線策略掃描頁面。

功能：run pipeline，查詢 scan_results，TradingView 匯出
"""

from __future__ import annotations

import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent.parent))

from datetime import date

import streamlit as st

from ui.components.command_preview import render_command_preview
from ui.components.layout import inject_css, section_header, status_badge_html
from ui.components.log_viewer import render_log_tail
from ui.components.result_table import render_scan_results
from ui.services.command_runner import get_store, launch_task, poll_all_running, poll_task
from ui.services.command_specs import RUN
from ui.services.db import get_engine
from ui.services.queries import (
    get_available_scan_dates,
    get_available_strategies,
    get_scan_results,
)

st.set_page_config(page_title="Daily Scan | Sentinel", layout="wide")
inject_css()
st.title("📊 Daily Scan")
st.caption("執行完整 Pipeline（抓價格 → 計算指標 → 策略掃描）並查詢結果")

store = get_store()
_just_finished = [t for t in poll_all_running() if t.status in ("success", "failed")]

# ── 資料庫 ─────────────────────────────────────────────────────────────────
try:
    engine = get_engine()
    db_ok = True
except Exception as e:
    st.error(str(e))
    db_ok = False

# ═══════════════════════════════════════════════════════════════════════════
# 區塊 A：執行 Pipeline
# ═══════════════════════════════════════════════════════════════════════════
section_header("執行 Pipeline（run）", "送出後長任務在背景執行，可至 Task Center 追蹤")

today = date.today()

with st.form("run_form"):
    c1, c2 = st.columns(2)
    start_date = c1.date_input("開始日期 *", value=today)
    end_date = c2.date_input("結束日期 *", value=today)

    with st.expander("進階選項"):
        ec1, ec2, ec3 = st.columns(3)
        trading_date = ec1.date_input("掃描交易日（留空=結束日期）", value=None)
        direction = ec2.selectbox("方向篩選", ["", "long", "short"], index=0)
        markets = ec3.multiselect("市場", ["TWSE", "TPEX"], default=[])
        ec4, ec5 = st.columns(2)
        skip_indicators = ec4.checkbox("跳過技術指標計算")
        skip_strategies = ec5.checkbox("跳過策略掃描")
        strategy_path = st.text_input(
            "策略設定檔路徑（留空=預設）", placeholder="config/strategies.json"
        )

    # Command Preview
    params: dict = {
        "start-date": start_date.isoformat(),
        "end-date": end_date.isoformat(),
    }
    if trading_date:
        params["trading-date"] = trading_date.isoformat()
    if direction:
        params["direction"] = direction
    if markets:
        params["market"] = markets
    if skip_indicators:
        params["skip-indicators"] = True
    if skip_strategies:
        params["skip-strategies"] = True
    if strategy_path:
        params["strategy-path"] = strategy_path

    render_command_preview(RUN, params)

    submitted = st.form_submit_button("▶ 執行 Run", use_container_width=True)

if submitted:
    if start_date > end_date:
        st.error("開始日期不可晚於結束日期")
    else:
        task = launch_task(RUN, params)
        st.session_state["last_run_task"] = task.task_id
        if task.status in ("success", "failed"):
            st.rerun()
        else:
            st.info(f"任務已送出（#{task.task_id}），請至 Task Center 追蹤進度")
            st.rerun()

# 最近一次執行結果
if "last_run_task" in st.session_state:
    task = poll_task(st.session_state["last_run_task"])
    st.markdown(
        status_badge_html(task.status) + f" Task `{task.task_id}` · 耗時 {task.duration_str}",
        unsafe_allow_html=True,
    )
    if task.stdout_tail or task.stderr_tail:
        render_log_tail(task.stdout_tail, task.stderr_tail)
    if task.status == "running":
        st.info("⏳ 任務執行中，頁面每 5 秒自動更新…")
        time.sleep(5)
        st.rerun()

st.divider()

# ═══════════════════════════════════════════════════════════════════════════
# 區塊 B：查詢掃描結果
# ═══════════════════════════════════════════════════════════════════════════
section_header("查詢掃描結果", "從資料庫讀取 scan_results，支援多條件篩選")

if not db_ok:
    st.warning("資料庫未連線，無法查詢結果")
else:
    available_dates = get_available_scan_dates(engine, limit=60)
    available_strategies = get_available_strategies(engine)

    f1, f2, f3, f4 = st.columns(4)
    sel_date = f1.selectbox(
        "交易日",
        ["全部"] + [str(d) for d in available_dates],
        index=1 if available_dates else 0,
    )
    sel_market = f2.selectbox("市場", ["全部", "TWSE", "TPEX"])
    sel_strategy = f3.selectbox("策略", ["全部"] + available_strategies)
    sel_direction = f4.selectbox("方向", ["全部", "long", "short"])

    query_date = date.fromisoformat(sel_date) if sel_date != "全部" else None
    query_market = sel_market if sel_market != "全部" else None
    query_strategy = sel_strategy if sel_strategy != "全部" else None
    query_direction = sel_direction if sel_direction != "全部" else None

    results_df = get_scan_results(
        engine,
        trading_date=query_date,
        market=query_market,
        strategy_id=query_strategy,
        direction=query_direction,
        limit=500,
    )

    render_scan_results(results_df)
