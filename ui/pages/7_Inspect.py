"""Inspect — 資料庫狀態與日誌檢查頁面。

子頁籤：status | completeness | results | logs | intraday-trades
"""

from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent.parent))

from datetime import date

import streamlit as st

from ui.components.command_preview import render_command_preview
from ui.components.layout import inject_css, section_header, status_badge_html
from ui.components.log_viewer import render_log_tail
from ui.components.result_table import render_df, render_scan_results
from ui.services.command_runner import get_store, launch_task, poll_task
from ui.services.command_specs import (
    INSPECT_COMPLETENESS,
    INSPECT_INTRADAY_TRADES,
    INSPECT_LOGS,
    INSPECT_RESULTS,
    INSPECT_STATUS,
)
from ui.services.db import get_engine
from ui.services.queries import (
    get_available_scan_dates,
    get_available_strategies,
    get_data_freshness,
    get_latest_job_runs,
    get_quarantine_summary,
    get_scan_results,
)

st.set_page_config(page_title="Inspect | Sentinel", layout="wide")
inject_css()
st.title("🔍 Inspect")
st.caption("資料完整性、掃描結果、Job 日誌、隔離記錄")

store = get_store()

try:
    engine = get_engine()
    db_ok = True
except Exception as e:
    st.error(str(e))
    db_ok = False

tab_status, tab_completeness, tab_results, tab_logs, tab_intraday = st.tabs(
    ["Status", "Completeness", "Results", "Logs", "Intraday Trades"]
)


def _show_cli_task(task_key: str) -> None:
    """統一顯示 CLI 任務結果（避免重複渲染）。"""
    if task_key not in st.session_state:
        return
    task = poll_task(st.session_state[task_key])
    st.markdown(
        status_badge_html(task.status) + f" · Task `{task.task_id}` · 耗時 {task.duration_str}",
        unsafe_allow_html=True,
    )
    if task.stdout_tail or task.stderr_tail:
        render_log_tail(task.stdout_tail, task.stderr_tail)


# ═══════════════════════════════════════════════════════════════════════════
# Tab 1: Status
# ═══════════════════════════════════════════════════════════════════════════
with tab_status:
    section_header("資料狀態", "顯示各資料表最新日期（inspect status）")

    render_command_preview(INSPECT_STATUS, {})

    if st.button("▶ 執行 inspect status", key="btn_status"):
        task = launch_task(INSPECT_STATUS, {})
        st.session_state["inspect_status_task"] = task.task_id
        st.rerun()

    _show_cli_task("inspect_status_task")

    # DB 直讀摘要
    if db_ok:
        st.divider()
        section_header("DB 直讀摘要")
        fresh_df = get_data_freshness(engine)
        if not fresh_df.empty:
            render_df(
                fresh_df, title="股價資料新鮮度", download_filename="freshness.csv", height=200
            )
        else:
            st.info("尚無股價資料")
        quar = get_quarantine_summary(engine)
        c1, c2 = st.columns(2)
        c1.metric("隔離記錄總數", quar["total"])
        c2.metric("待處理隔離", quar["pending"])
        if not quar["recent"].empty:
            render_df(
                quar["recent"], title="最近隔離記錄", download_filename="quarantine.csv", height=200
            )


# ═══════════════════════════════════════════════════════════════════════════
# Tab 2: Completeness
# ═══════════════════════════════════════════════════════════════════════════
with tab_completeness:
    section_header("資料完整性檢查", "inspect completeness --date YYYY-MM-DD")

    check_date = st.date_input("目標日期 *", value=date.today(), key="comp_date")
    params_c = {"date": check_date.isoformat()}

    render_command_preview(INSPECT_COMPLETENESS, params_c)

    if st.button("▶ 執行 inspect completeness", key="btn_comp"):
        task = launch_task(INSPECT_COMPLETENESS, params_c)
        st.session_state["inspect_comp_task"] = task.task_id
        st.rerun()

    _show_cli_task("inspect_comp_task")


# ═══════════════════════════════════════════════════════════════════════════
# Tab 3: Results
# ═══════════════════════════════════════════════════════════════════════════
with tab_results:
    section_header("掃描結果查詢", "DB 直讀（支援方向、日期、策略、市場篩選）")

    if db_ok:
        available_dates = get_available_scan_dates(engine, limit=60)
        available_strats = get_available_strategies(engine)

        r1, r2, r3, r4, r5 = st.columns(5)
        sel_date = r1.selectbox(
            "日期",
            ["最新"] + [str(d) for d in available_dates],
            index=0,
            key="res_date",
        )
        sel_dir = r2.selectbox("方向", ["全部", "long", "short"], key="res_dir")
        sel_strat = r3.selectbox("策略", ["全部"] + available_strats, key="res_strat")
        sel_mkt = r4.selectbox("市場", ["全部", "TWSE", "TPEX"], key="res_mkt")
        limit = r5.number_input(
            "最大筆數", value=100, min_value=1, max_value=1000, step=50, key="res_lim"
        )

        q_date = (
            date.fromisoformat(sel_date)
            if sel_date != "最新"
            else (available_dates[0] if available_dates else None)
        )
        q_dir = sel_dir if sel_dir != "全部" else None
        q_strat = sel_strat if sel_strat != "全部" else None
        q_mkt = sel_mkt if sel_mkt != "全部" else None

        df = get_scan_results(
            engine,
            trading_date=q_date,
            market=q_mkt,
            strategy_id=q_strat,
            direction=q_dir,
            limit=int(limit),
        )
        render_scan_results(df)
    else:
        st.warning("資料庫未連線")

    # CLI 補充查詢
    st.divider()
    section_header("透過 CLI 查詢（inspect results）")
    with st.expander("CLI 參數", expanded=False):
        cli_cols = st.columns(4)
        cli_strat = cli_cols[0].text_input("策略 ID", key="cli_res_strat")
        cli_date = cli_cols[1].date_input("日期", value=None, key="cli_res_date")
        cli_dir = cli_cols[2].selectbox("方向", ["", "long", "short"], key="cli_res_dir")
        cli_limit = cli_cols[3].number_input(
            "最大筆數", value=50, min_value=1, max_value=500, key="cli_res_lim"
        )

        params_r: dict = {"limit": int(cli_limit)}
        if cli_strat:
            params_r["strategy"] = cli_strat
        if cli_date:
            params_r["date"] = cli_date.isoformat()
        if cli_dir:
            params_r["direction"] = cli_dir

        render_command_preview(INSPECT_RESULTS, params_r)
        if st.button("▶ inspect results (CLI)", key="btn_cli_results"):
            task = launch_task(INSPECT_RESULTS, params_r)
            st.session_state["inspect_cli_results_task"] = task.task_id
            st.rerun()

    _show_cli_task("inspect_cli_results_task")


# ═══════════════════════════════════════════════════════════════════════════
# Tab 4: Logs
# ═══════════════════════════════════════════════════════════════════════════
with tab_logs:
    section_header("Job / Quarantine 日誌")

    l1, l2 = st.columns(2)
    log_type = l1.radio("日誌類型", ["jobs", "quarantine"], horizontal=True)
    log_limit = l2.slider("顯示筆數", 10, 200, 20)

    params_l = {"type": log_type, "limit": log_limit}
    render_command_preview(INSPECT_LOGS, params_l)

    if st.button("▶ 執行 inspect logs", key="btn_logs"):
        task = launch_task(INSPECT_LOGS, params_l)
        st.session_state["inspect_logs_task"] = task.task_id
        st.rerun()

    _show_cli_task("inspect_logs_task")

    # DB 直讀
    if db_ok:
        st.divider()
        section_header("DB 直讀：JobRun 記錄")
        job_df = get_latest_job_runs(engine, limit=int(log_limit))
        render_df(job_df, title="JobRun", download_filename="job_runs.csv", height=300)


# ═══════════════════════════════════════════════════════════════════════════
# Tab 5: Intraday Trades
# ═══════════════════════════════════════════════════════════════════════════
with tab_intraday:
    section_header("模擬交易日誌", "inspect intraday-trades")

    export_csv = st.checkbox("同時匯出 CSV 到 outputs/reports/", key="intra_export")
    params_i: dict = {}
    if export_csv:
        params_i["export"] = True

    render_command_preview(INSPECT_INTRADAY_TRADES, params_i)

    if st.button("▶ 執行 inspect intraday-trades", key="btn_intra"):
        task = launch_task(INSPECT_INTRADAY_TRADES, params_i)
        st.session_state["inspect_intra_task"] = task.task_id
        st.rerun()

    _show_cli_task("inspect_intra_task")
