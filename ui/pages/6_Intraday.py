"""Intraday — 盤中監控與操作頁面（Phase C）。"""

from __future__ import annotations

import io
import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent.parent))

import pandas as pd
import streamlit as st

from ui.components.command_preview import render_command_preview
from ui.components.layout import inject_css, section_header, status_badge_html
from ui.components.log_viewer import render_log_tail
from ui.services.command_runner import get_store, launch_task, poll_all_running, poll_task
from ui.services.command_specs import (
    ADD_INTRADAY_TRADE,
    CAPTURE_SNAPSHOT,
    CLEAR_INTRADAY_TRADES,
    MONITOR_INTRADAY_TRADES,
    RUN_INTRADAY,
    SCHEDULER,
    UPDATE_INTRADAY_STATS,
    UPDATE_INTRADAY_TRADES,
)
from ui.services.db import get_engine
from ui.services.queries import get_intraday_trades

st.set_page_config(page_title="Intraday | Sentinel", layout="wide")
inject_css()
st.title("⏱ Intraday")
st.caption("盤中快照、明日之星掃描、模擬交易監控")

store = get_store()
poll_all_running()

tab_snapshot, tab_run, tab_trades, tab_scheduler = st.tabs(
    ["盤中快照", "明日之星掃描", "模擬交易", "Scheduler"]
)


def _parse_tomorrow_star_table(stdout: str) -> pd.DataFrame | None:
    """從 CLI 的 to_string() 輸出解析明日之星結果表格。"""
    lines = stdout.splitlines()
    header_idx = next((i for i, l in enumerate(lines) if "市場" in l and "代號" in l), None)
    if header_idx is None:
        return None
    table_lines = []
    for l in lines[header_idx:]:
        if "====" in l:
            break
        table_lines.append(l)
    if len(table_lines) < 2:
        return None
    try:
        return pd.read_csv(
            io.StringIO("\n".join(table_lines)),
            sep=r"\s{2,}",
            engine="python",
        )
    except Exception:
        return None


def _show_task(task_key: str) -> None:
    if task_key not in st.session_state:
        return
    task = poll_task(st.session_state[task_key])
    st.markdown(
        status_badge_html(task.status) + f" · 耗時 {task.duration_str}",
        unsafe_allow_html=True,
    )
    if task.status == "running":
        st.info("⏳ 掃描中，每 5 秒自動更新…")
        time.sleep(5)
        st.rerun()
    if task.stdout_tail or task.stderr_tail:
        # 若 success，先嘗試解析成表格
        if task.status == "success" and task.stdout_tail:
            df = _parse_tomorrow_star_table(task.stdout_tail)
            if df is not None and not df.empty:
                # 計算結果數量（不含標題行）
                n = len(df)
                st.success(f"🌟 掃描完成，找到 {n} 檔符合條件")
                st.dataframe(df, use_container_width=True, hide_index=True)
        render_log_tail(task.stdout_tail, task.stderr_tail)


# ── 盤中快照 ───────────────────────────────────────────────────────────────
with tab_snapshot:
    # 30 秒自動刷新（fragment 不重繪整頁）
    auto_refresh = st.checkbox("🔄 每 30 秒自動刷新", value=False, key="snap_auto")

    @st.fragment(run_every=30 if auto_refresh else None)
    def _snapshot_section() -> None:
        section_header("擷取盤中快照（capture-intraday-snapshot）")
        sn1, sn2 = st.columns(2)
        snap_time = sn1.text_input("快照時間標籤", value="12:00", key="snap_time_f")
        snap_top = sn2.number_input(
            "Top N 檔", value=300, min_value=50, max_value=1000, key="snap_top_f"
        )
        params_snap = {"time": snap_time, "top": int(snap_top)}
        render_command_preview(CAPTURE_SNAPSHOT, params_snap)
        if st.button("▶ 擷取快照", key="btn_snap_f"):
            task = launch_task(CAPTURE_SNAPSHOT, params_snap)
            st.session_state["snap_task"] = task.task_id
            task = poll_task(task.task_id)
            render_log_tail(task.stdout_tail, task.stderr_tail)

    _snapshot_section()

    st.divider()
    section_header("更新日內統計（update-intraday-stats）")
    lb_days = st.number_input("回溯天數", value=180, min_value=30, max_value=730, key="lb_days")
    params_stat = {"lookback-days": int(lb_days)}
    render_command_preview(UPDATE_INTRADAY_STATS, params_stat)
    if st.button("▶ 更新統計", key="btn_stat"):
        task = launch_task(UPDATE_INTRADAY_STATS, params_stat)
        st.session_state["stat_task"] = task.task_id
        task = poll_task(task.task_id)
        render_log_tail(task.stdout_tail, task.stderr_tail)


# ── 明日之星 ───────────────────────────────────────────────────────────────
with tab_run:
    section_header("明日之星掃描（run-intraday）")
    ri1, ri2 = st.columns(2)
    ri_top = ri1.number_input("監控 Top N", value=300, min_value=50, max_value=1000, key="ri_top")
    ri_gain = ri2.number_input(
        "最低漲幅門檻", value=0.075, min_value=0.01, max_value=0.30, step=0.005, key="ri_gain"
    )
    ri_tg = st.checkbox("傳送 Telegram 通知", key="ri_tg")
    params_ri: dict = {"top": int(ri_top), "min-gain": float(ri_gain)}
    if ri_tg:
        params_ri["notify-telegram"] = True

    render_command_preview(RUN_INTRADAY, params_ri)
    if st.button("▶ 執行明日之星掃描", key="btn_ri"):
        task = launch_task(RUN_INTRADAY, params_ri)
        st.session_state["ri_task"] = task.task_id
        st.info(f"任務已送出（#{task.task_id}），請至 Task Center 追蹤")
        st.rerun()

    _show_task("ri_task")


# ── 模擬交易 ───────────────────────────────────────────────────────────────
with tab_trades:
    section_header("模擬交易操作")

    # ── 目前持倉總覽 ──────────────────────────────────────────────────────────
    st.markdown("##### 目前持倉")
    try:
        _engine = get_engine()
        _open_df = get_intraday_trades(_engine, status="open")
        _all_df = get_intraday_trades(_engine)
        _closed_count = len(_all_df[_all_df["狀態"] == "closed"]) if not _all_df.empty else 0
    except Exception as _e:
        _open_df = pd.DataFrame()
        _closed_count = 0
        st.warning(f"無法讀取持倉資料：{_e}")

    if _open_df.empty:
        st.info("目前無未平倉部位")
    else:
        oc1, oc2 = st.columns(2)
        oc1.metric("未平倉", len(_open_df))
        oc2.metric("已結算", _closed_count)
        display_cols = ["代號", "名稱", "市場", "進場日", "進場價", "備註"]
        st.dataframe(
            _open_df[display_cols].reset_index(drop=True),
            use_container_width=True,
            hide_index=True,
        )

    with st.expander("查看全部交易紀錄（含已結算）"):
        if not _all_df.empty:
            st.dataframe(
                _all_df.drop(columns=["trade_id"]), use_container_width=True, hide_index=True
            )
        else:
            st.info("尚無任何交易紀錄")

    st.divider()

    # 監控未平倉
    st.markdown("##### 監控未平倉（monitor-intraday-trades）")
    mt1, mt2 = st.columns(2)
    mon_thr = mt1.number_input(
        "停利/停損門檻", value=0.02, min_value=0.005, max_value=0.2, step=0.005, key="mon_thr"
    )
    mon_force = mt2.checkbox("強制平倉全部", key="mon_force")
    params_mon: dict = {"threshold": float(mon_thr)}
    if mon_force:
        params_mon["force-close"] = True
    render_command_preview(MONITOR_INTRADAY_TRADES, params_mon)
    if st.button("▶ 監控交易", key="btn_mon"):
        task = launch_task(MONITOR_INTRADAY_TRADES, params_mon)
        st.session_state["mon_task"] = task.task_id
        task = poll_task(task.task_id)
        render_log_tail(task.stdout_tail, task.stderr_tail)

    st.divider()

    # 結算前一日交易
    st.markdown("##### 結算昨日交易（update-intraday-trades）")
    ut1, ut2 = st.columns(2)
    ut_rt = ut1.checkbox("使用即時開盤價（MIS）", key="ut_rt")
    ut_pt = ut2.selectbox("結算價格類型", ["open", "last"], key="ut_pt")
    params_ut: dict = {"price-type": ut_pt}
    if ut_rt:
        params_ut["real-time"] = True
    render_command_preview(UPDATE_INTRADAY_TRADES, params_ut)
    if st.button("▶ 結算昨日交易", key="btn_ut"):
        task = launch_task(UPDATE_INTRADAY_TRADES, params_ut)
        st.session_state["ut_task"] = task.task_id
        task = poll_task(task.task_id)
        render_log_tail(task.stdout_tail, task.stderr_tail)

    st.divider()

    # 手動新增交易
    st.markdown("##### 手動新增模擬交易（add-intraday-trade）")
    with st.form("add_trade_form"):
        at1, at2, at3 = st.columns(3)
        at_sym = at1.text_input("股票代號 *")
        at_price = at2.number_input("進場價格 *", value=0.01, min_value=0.01, step=0.01)
        at_mkt = at3.selectbox("市場（留空自動）", ["", "TWSE", "TPEX"])
        at_notes = st.text_input("備註")
        params_at_preview: dict = {"symbol": "（代號）", "price": "（價格）"}
        render_command_preview(ADD_INTRADAY_TRADE, params_at_preview)
        add_submitted = st.form_submit_button("▶ 新增交易", use_container_width=True)

    if add_submitted:
        if not at_sym or at_price <= 0:
            st.error("請填寫有效的股票代號與進場價格")
        else:
            params_at: dict = {"symbol": at_sym.strip(), "price": float(at_price)}
            if at_mkt:
                params_at["market"] = at_mkt
            if at_notes:
                params_at["notes"] = at_notes
            task = launch_task(ADD_INTRADAY_TRADE, params_at)
            task = poll_task(task.task_id)
            if task.status == "success":
                st.success(f"已新增 {at_sym.strip()} 至模擬交易")
                st.rerun()
            else:
                render_log_tail(task.stdout_tail, task.stderr_tail)

    st.divider()

    # 清除所有交易（雙重確認）
    st.markdown("##### 清除所有模擬交易（clear-intraday-trades）")
    render_command_preview(CLEAR_INTRADAY_TRADES, {})
    clear_col1, clear_col2 = st.columns([3, 1])
    with clear_col2:
        if st.button("⚠️ 清除所有交易", key="btn_clear_init", use_container_width=True):
            st.session_state["clear_confirm_pending"] = True

    if st.session_state.get("clear_confirm_pending"):
        st.warning("⚠️ 此操作不可還原！確認清除所有模擬交易記錄？")
        conf1, conf2 = st.columns(2)
        if conf1.button("✅ 確認清除", key="btn_clear_confirm", use_container_width=True):
            st.session_state.pop("clear_confirm_pending", None)
            task = launch_task(CLEAR_INTRADAY_TRADES, {})
            task = poll_task(task.task_id)
            render_log_tail(task.stdout_tail, task.stderr_tail)
        if conf2.button("❌ 取消", key="btn_clear_cancel", use_container_width=True):
            st.session_state.pop("clear_confirm_pending", None)
            st.rerun()


# ── Scheduler ─────────────────────────────────────────────────────────────
with tab_scheduler:
    section_header("自動化排程器（scheduler）")
    st.warning(
        "Scheduler 啟動後為常駐程序（APScheduler），關閉 UI 不會停止排程器。"
        "請至 Task Center 確認其 PID。"
    )
    render_command_preview(SCHEDULER, {})

    # 檢查是否已有 scheduler 在執行
    scheduler_tasks = [t for t in store.list_all() if t.command_id == "scheduler"]
    running_schedulers = [t for t in scheduler_tasks if t.status == "running"]
    if running_schedulers:
        st.success(
            f"✅ Scheduler 已在執行中（Task #{running_schedulers[0].task_id}，PID {running_schedulers[0].pid}）"
        )
    else:
        if st.button("▶ 啟動 Scheduler", key="btn_scheduler"):
            task = launch_task(SCHEDULER, {})
            st.success(f"Scheduler 已啟動（PID: {task.pid}），Task ID: {task.task_id}")
            st.info("請至 Task Center 查看狀態")
            st.rerun()
