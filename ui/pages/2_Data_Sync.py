"""Data Sync — 資料同步頁面。

功能：init-db, sync-calendar, sync-stocks, sync, backfill-yahoo, sync-institutional
"""

from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent.parent))

import streamlit as st

from ui.components.command_preview import render_command_preview
from ui.components.form_factory import render_form
from ui.components.layout import inject_css, section_header, status_badge_html
from ui.components.log_viewer import render_log_tail
from ui.services.command_runner import (
    find_running_task,
    get_store,
    launch_task,
    poll_all_running,
    poll_task,
)
from ui.services.command_specs import (
    BACKFILL_YAHOO,
    INIT_DB,
    SYNC,
    SYNC_CALENDAR,
    SYNC_INSTITUTIONAL,
    SYNC_MAIN_FORCE,
    SYNC_STOCKS,
)

st.set_page_config(page_title="Data Sync | Sentinel", layout="wide")
inject_css()
st.title("🔄 Data Sync")
st.caption("資料庫初始化、行事曆、股票主檔、股價補齊、法人籌碼")

store = get_store()
poll_all_running()

# ── 執行中任務提示 ─────────────────────────────────────────────────────────
running = store.list_by_status("running")
if running:
    st.warning(f"⚙️ {len(running)} 個任務執行中 — 請前往 [Task Center](/9_Task_Center) 查看進度")


def _show_task_result(task_key: str) -> None:
    """顯示指定 session_state key 的任務結果（去重複顯示）。"""
    if task_key not in st.session_state:
        return
    task = poll_task(st.session_state[task_key])
    st.markdown(
        status_badge_html(task.status) + f" Task `{task.task_id}` · 耗時 {task.duration_str}",
        unsafe_allow_html=True,
    )
    if task.stdout_tail or task.stderr_tail:
        render_log_tail(task.stdout_tail, task.stderr_tail)


def _run_section(spec, section_key: str) -> None:
    """渲染單一指令區塊：表單 → Command Preview → 執行 → 結果。"""
    st.markdown(f"##### {spec.description}")
    params = render_form(spec, prefix=section_key)

    preview_col, run_col = st.columns([5, 1])
    with preview_col:
        render_command_preview(spec, params)
    with run_col:
        st.write("")
        st.write("")
        clicked = st.button("▶ 執行", key=f"btn_{section_key}", use_container_width=True)

    if clicked:
        if spec.validator:
            err = spec.validator(params)
            if err:
                st.error(f"參數錯誤：{err}")
                return
        running = find_running_task(spec.command_id)
        if running:
            st.warning(
                f"⚠️ {spec.command_id} 已在執行中（#{running.task_id}），請至 [Task Center](/9_Task_Center) 查看"
            )
            return
        task = launch_task(spec, params)
        st.session_state[f"task_{section_key}"] = task.task_id
        # 短任務直接完成，長任務送出後通知
        if task.status in ("success", "failed"):
            st.rerun()
        else:
            st.info(f"任務已送出（#{task.task_id}），長任務請至 Task Center 追蹤")
            st.rerun()

    _show_task_result(f"task_{section_key}")


# ── 各指令區塊 ─────────────────────────────────────────────────────────────
SECTIONS = [
    ("初始化資料庫", INIT_DB, "init_db"),
    ("行事曆同步", SYNC_CALENDAR, "sync_cal"),
    ("股票主檔同步", SYNC_STOCKS, "sync_stocks"),
    ("自動補齊股價", SYNC, "sync"),
    ("Yahoo Finance 補資料", BACKFILL_YAHOO, "backfill_yahoo"),
    ("法人籌碼同步", SYNC_INSTITUTIONAL, "sync_institutional"),
    ("主力分點同步", SYNC_MAIN_FORCE, "sync_main_force"),
]

for title, spec, key in SECTIONS:
    section_header(title)
    _run_section(spec, key)
    st.divider()
