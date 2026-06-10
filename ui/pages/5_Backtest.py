"""Backtest — 回測中心頁面（Phase B）。"""

from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent.parent))

from datetime import date, timedelta

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from ui.components.command_preview import render_command_preview
from ui.components.layout import inject_css, section_header, status_badge_html
from ui.components.log_viewer import render_log_tail
from ui.components.result_table import render_df
from ui.services.backtest_compare import (
    build_equity_curves,
    discover_backtest_runs,
    load_run_report,
)
from ui.services.command_runner import get_store, launch_task, poll_all_running, poll_task
from ui.services.command_specs import BACKFILL_AGG_BARS, BACKTEST, IMPORT_MINUTE_BARS

st.set_page_config(page_title="Backtest | Sentinel", layout="wide")
inject_css()
st.title("🧪 Backtest")
st.caption("匯入分鐘線、補建聚合 K 棒、回測執行與報表查詢")

store = get_store()
poll_all_running()

tab_import, tab_backfill, tab_run, tab_compare = st.tabs(
    ["匯入分鐘線", "補建聚合 K 棒", "執行回測", "📊 比較"]
)


def _show_task(task_key: str) -> None:
    if task_key not in st.session_state:
        return
    task = poll_task(st.session_state[task_key])
    st.markdown(
        status_badge_html(task.status) + f" · 耗時 {task.duration_str}",
        unsafe_allow_html=True,
    )
    if task.stdout_tail or task.stderr_tail:
        render_log_tail(task.stdout_tail, task.stderr_tail)


# ── 匯入分鐘線 ─────────────────────────────────────────────────────────────
with tab_import:
    section_header("匯入 FinMind 分鐘線 CSV（import-minute-bars）")
    csv_path = st.text_input("CSV 檔案路徑 *", placeholder="/path/to/finmind_1m.csv", key="imp_csv")
    chunk_size = st.number_input(
        "批次大小", value=100000, min_value=1000, max_value=1000000, step=10000, key="imp_chunk"
    )
    params_imp: dict = {"chunk-size": int(chunk_size)}
    if csv_path:
        params_imp["csv"] = csv_path
    render_command_preview(IMPORT_MINUTE_BARS, params_imp)
    if st.button("▶ 匯入", key="btn_import"):
        if not csv_path:
            st.error("請輸入 CSV 路徑")
        else:
            task = launch_task(IMPORT_MINUTE_BARS, params_imp)
            st.session_state["import_task"] = task.task_id
            st.info(f"任務已送出（#{task.task_id}），請至 Task Center 追蹤")
            st.rerun()
    _show_task("import_task")

# ── 補建聚合 K 棒 ──────────────────────────────────────────────────────────
with tab_backfill:
    section_header("補建 3 日 / 47 日聚合 K 棒（backfill-aggregated-bars）")
    render_command_preview(BACKFILL_AGG_BARS, {})
    if st.button("▶ 補建聚合 K 棒", key="btn_agg"):
        task = launch_task(BACKFILL_AGG_BARS, {})
        st.session_state["agg_task"] = task.task_id
        st.info(f"任務已送出（#{task.task_id}），請至 Task Center 追蹤")
        st.rerun()
    _show_task("agg_task")

# ── 執行回測 ───────────────────────────────────────────────────────────────
with tab_run:
    section_header("執行回測（backtest）")
    today = date.today()
    with st.form("backtest_form"):
        c1, c2 = st.columns(2)
        start_date = c1.date_input("開始日期 *", value=today - timedelta(days=365))
        end_date = c2.date_input("結束日期 *", value=today)

        with st.expander("回測參數", expanded=True):
            ec1, ec2 = st.columns(2)
            exec_model = ec1.selectbox("執行模型", ["daily", "minute_bar"])
            strat_mode = ec2.selectbox("策略模式", ["standard", "tomorrow_star"])
            ec3, ec4, ec5 = st.columns(3)
            symbol_filter = ec3.text_input("限定股票代號（留空=全部）")
            initial_cap = ec4.number_input(
                "初始資金（0=無限制）", value=0, min_value=0, step=100000
            )
            position_size = ec5.number_input("單筆金額", value=100000, min_value=1000, step=10000)

        params_bt: dict = {
            "start-date": start_date.isoformat(),
            "end-date": end_date.isoformat(),
            "execution-model": exec_model,
            "strategy-mode": strat_mode,
            "position-size": position_size,
        }
        if symbol_filter:
            params_bt["symbol"] = symbol_filter
        if initial_cap > 0:
            params_bt["initial-capital"] = initial_cap

        render_command_preview(BACKTEST, params_bt)
        bt_submitted = st.form_submit_button("▶ 執行回測", use_container_width=True)

    if bt_submitted:
        if start_date > end_date:
            st.error("開始日期不可晚於結束日期")
        else:
            task = launch_task(BACKTEST, params_bt)
            st.session_state["backtest_task"] = task.task_id
            st.info(f"任務已送出（#{task.task_id}），請至 Task Center 追蹤進度")
            st.rerun()

    _show_task("backtest_task")

    # ── 回測報表瀏覽 ────────────────────────────────────────────────────────
    st.divider()
    section_header("回測報表瀏覽", "自動搜尋 outputs/ 目錄下最新的 report.csv / trades.csv")

    outputs_dir = pathlib.Path(__file__).parent.parent.parent / "outputs"
    report_files = sorted(
        outputs_dir.glob("**/report.csv"), key=lambda p: p.stat().st_mtime, reverse=True
    )
    trades_files = sorted(
        outputs_dir.glob("**/trades.csv"), key=lambda p: p.stat().st_mtime, reverse=True
    )

    if not report_files and not trades_files:
        st.info("尚無回測報表，請先執行回測")
    else:
        rep_tab, trd_tab = st.tabs(["績效報表 (report.csv)", "逐筆明細 (trades.csv)"])

        with rep_tab:
            if report_files:
                sel_rep = st.selectbox(
                    "選擇報表",
                    [str(f.relative_to(outputs_dir)) for f in report_files],
                    key="sel_rep",
                )
                rep_path = outputs_dir / sel_rep
                try:
                    rep_df = pd.read_csv(str(rep_path))
                    render_df(rep_df, title="績效摘要", download_filename="report.csv")
                except Exception as e:
                    st.error(f"讀取報表失敗：{e}")
            else:
                st.info("尚無 report.csv")

        with trd_tab:
            if trades_files:
                sel_trd = st.selectbox(
                    "選擇明細",
                    [str(f.relative_to(outputs_dir)) for f in trades_files],
                    key="sel_trd",
                )
                trd_path = outputs_dir / sel_trd
                try:
                    trd_df = pd.read_csv(str(trd_path))
                    render_df(trd_df, title="逐筆交易", download_filename="trades.csv", height=500)
                except Exception as e:
                    st.error(f"讀取明細失敗：{e}")
            else:
                st.info("尚無 trades.csv")

# ── 比較 ───────────────────────────────────────────────────────────────────
with tab_compare:
    section_header("回測結果比較", "選擇多個 run 比較績效指標與權益曲線")

    backtests_dir = pathlib.Path("outputs/backtests")
    runs = discover_backtest_runs(backtests_dir)

    if not runs:
        st.info("尚無回測結果，請先執行回測")
    else:
        run_ids = [r["run_id"] for r in runs]
        selected = st.multiselect(
            "選擇要比較的回測 run",
            run_ids,
            default=run_ids[:2],
            key="cmp_runs",
        )
        run_by_id = {r["run_id"]: r for r in runs}

        if not selected:
            st.info("請至少選擇一個 run")
        else:
            # ── 績效指標表 ──────────────────────────────────────────────
            report_frames: list[pd.DataFrame] = []
            for run_id in selected:
                try:
                    report_frames.append(load_run_report(run_by_id[run_id]["path"]))
                except Exception as e:
                    st.warning(f"讀取 {run_id} 的 report.csv 失敗：{e}")
            if report_frames:
                metrics_df = pd.concat(report_frames, ignore_index=True)
                show_cols = [
                    "run_id",
                    "strategy_id",
                    "trades",
                    "win_rate",
                    "total_return",
                    "cagr",
                    "mdd",
                ]
                st.dataframe(
                    metrics_df[[c for c in show_cols if c in metrics_df.columns]],
                    use_container_width=True,
                    hide_index=True,
                )

            # ── 權益曲線疊圖 ────────────────────────────────────────────
            fig = go.Figure()
            for run_id in selected:
                trades_path = run_by_id[run_id]["path"] / "trades.csv"
                try:
                    trades_df = pd.read_csv(trades_path)
                    curves = build_equity_curves(trades_df)
                except Exception as e:
                    st.warning(f"讀取 {run_id} 的 trades.csv 失敗：{e}")
                    continue
                for strategy_id, curve in curves.groupby("strategy_id", sort=False):
                    fig.add_trace(
                        go.Scatter(
                            x=curve["exit_date"],
                            y=curve["balance"],
                            mode="lines+markers",
                            name=f"{run_id}/{strategy_id}",
                            line={"width": 1.5},
                        )
                    )
            if fig.data:
                fig.update_layout(
                    height=500,
                    margin={"l": 40, "r": 20, "t": 40, "b": 20},
                    legend={"orientation": "h", "y": 1.02},
                    plot_bgcolor="#0f172a",
                    paper_bgcolor="#0f172a",
                    font_color="#e2e8f0",
                    yaxis_title="權益 (balance)",
                )
                fig.update_xaxes(showgrid=False, zeroline=False)
                fig.update_yaxes(showgrid=True, gridcolor="#1e293b", zeroline=False)
                st.plotly_chart(fig, use_container_width=True)
            else:
                st.info("選取的 run 無可繪製的權益曲線")
