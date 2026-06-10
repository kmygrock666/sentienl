"""Command Preview 元件：執行前顯示完整指令字串。"""
from __future__ import annotations

import streamlit as st

from ui.services.command_specs import CommandSpec, argv_to_preview, build_argv


def render_command_preview(spec: CommandSpec, params: dict, *, show_copy: bool = True) -> list[str]:
    """
    依 spec + params 組合 argv，顯示唯讀的 command preview 區塊。
    回傳組合後的 argv list。
    """
    argv = build_argv(spec, params)
    preview = argv_to_preview(argv)
    st.code(preview, language="bash")
    return argv


def render_argv_preview(argv: list[str]) -> None:
    """直接顯示給定 argv list 的 preview。"""
    st.code(argv_to_preview(argv), language="bash")
