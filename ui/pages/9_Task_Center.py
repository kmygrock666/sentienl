"""Task Center — 全域任務佇列：執行中 / 成功 / 失敗 / 全部。"""
from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent.parent))

import streamlit as st

from ui.components.layout import inject_css
from ui.components.log_viewer import render_task_card
from ui.services.command_runner import get_store, poll_all_running, rerun_task

st.set_page_config(page_title="Task Center | Sentinel", layout="wide")
inject_css()
st.title("🗂 Task Center")
st.caption("所有 UI 任務的執行狀態、日誌與重跑入口")

store = get_store()

# ── 控制列 ─────────────────────────────────────────────────────────────────
ctrl1, ctrl2, ctrl3 = st.columns([1, 2, 5])
if ctrl1.button("🔄 手動刷新", use_container_width=True):
    poll_all_running()
    st.rerun()

filter_status = ctrl2.selectbox(
    "篩選狀態", ["全部", "running", "success", "failed", "pending"], index=0
)

# ── 執行中任務自動輪詢（每 3 秒刷新 fragment）─────────────────────────────
@st.fragment(run_every=3)
def _auto_poll() -> None:
    running = store.list_by_status("running")
    poll_all_running()
    if running:
        names = "、".join(t.command_id for t in running[:4])
        st.info(f"🔄 自動輪詢中 — {len(running)} 個任務執行中：{names}")

_auto_poll()

st.divider()

# ── 統計摘要 ───────────────────────────────────────────────────────────────
all_tasks = store.list_all()
running_cnt = sum(1 for t in all_tasks if t.status == "running")
success_cnt = sum(1 for t in all_tasks if t.status == "success")
failed_cnt = sum(1 for t in all_tasks if t.status == "failed")

m1, m2, m3, m4 = st.columns(4)
m1.metric("全部任務", len(all_tasks))
m2.metric("🟡 執行中", running_cnt)
m3.metric("🟢 成功", success_cnt)
m4.metric("🔴 失敗", failed_cnt)

st.divider()

# ── 任務列表 ───────────────────────────────────────────────────────────────
tasks = all_tasks if filter_status == "全部" else [t for t in all_tasks if t.status == filter_status]

_RESULT_PAGES = {
    "run": "pages/3_Daily_Scan.py",
    "check-stock": "pages/4_Stock_Check.py",
    "backtest": "pages/5_Backtest.py",
    "run-intraday": "pages/6_Intraday.py",
    "inspect-status": "pages/7_Inspect.py",
    "inspect-completeness": "pages/7_Inspect.py",
    "inspect-results": "pages/7_Inspect.py",
}

if not tasks:
    st.info("此狀態無任務記錄")
else:
    for task in tasks:
        col_main, col_action = st.columns([9, 1])
        with col_main:
            render_task_card(task)
        with col_action:
            if task.status in ("success", "failed"):
                action_col1, action_col2 = st.columns(2)
                if action_col1.button("重跑", key=f"rerun_{task.task_id}", use_container_width=True):
                    new_task = rerun_task(task)
                    st.success(f"已重跑 → #{new_task.task_id}")
                    st.rerun()
                result_page = _RESULT_PAGES.get(task.command_id)
                if result_page:
                    try:
                        action_col2.page_link(result_page, label="結果", use_container_width=True)
                    except Exception:
                        pass
            elif task.status == "running":
                st.caption("執行中…")
