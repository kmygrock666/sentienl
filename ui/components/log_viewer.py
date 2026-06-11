"""日誌檢視元件：顯示任務輸出尾端與狀態卡片。"""

from __future__ import annotations

from typing import TYPE_CHECKING

import streamlit as st

from ui.components.layout import status_badge_html

if TYPE_CHECKING:
    from ui.services.command_runner import TaskRun


def render_log_tail(stdout: str, stderr: str, max_chars: int = 6000) -> None:
    """顯示 stdout / stderr 尾端輸出。"""
    if stdout and stdout.strip():
        with st.expander("標準輸出（stdout）", expanded=True):
            tail = stdout[-max_chars:] if len(stdout) > max_chars else stdout
            st.code(tail, language="text")
    if stderr and stderr.strip():
        with st.expander("標準錯誤（stderr）", expanded=False):
            tail = stderr[-max_chars:] if len(stderr) > max_chars else stderr
            st.code(tail, language="text")


def render_task_card(task: TaskRun) -> None:
    """渲染單一任務卡片（狀態、指令預覽、時間、日誌）。"""
    with st.container():
        # 頂列：狀態 + 指令 ID + 時間
        c1, c2, c3 = st.columns([1, 5, 2])
        with c1:
            st.markdown(status_badge_html(task.status), unsafe_allow_html=True)
        with c2:
            st.caption(f"**{task.command_id}** · ID: `{task.task_id}`")
            st.code(task.argv_preview, language="bash")
        with c3:
            st.caption(f"開始：{task.started_at[:19] if task.started_at else '—'}")
            if task.ended_at:
                st.caption(f"結束：{task.ended_at[:19]}")
            st.caption(f"耗時：{task.duration_str}")
            if task.exit_code is not None:
                color = "#3FA66B" if task.exit_code == 0 else "#D84B4B"
                st.markdown(
                    f'<span style="color:{color};font-family:monospace">exit {task.exit_code}</span>',
                    unsafe_allow_html=True,
                )

        # 錯誤訊息（折疊前預覽）
        if task.error_message:
            st.error(f"錯誤：{task.error_message[:300]}")

        # 日誌展開
        if task.stdout_tail or task.stderr_tail:
            with st.expander("檢視日誌"):
                render_log_tail(task.stdout_tail, task.stderr_tail)

        st.divider()
