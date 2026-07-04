"""表單工廠：依 CommandSpec.fields 自動渲染 Streamlit 表單元件。"""

from __future__ import annotations

from datetime import date
from typing import Any

import streamlit as st

from ui.services.command_specs import CommandSpec, FieldSpec


def _render_field(f: FieldSpec, prefix: str, defaults: dict) -> Any:
    """渲染單一表單欄位，回傳使用者輸入值。"""
    key = f"{prefix}_{f.name}"
    default = defaults.get(f.name, f.default)
    label = f.label + (" *" if f.required else "")

    if f.type == "text":
        return st.text_input(
            label,
            value=str(default) if default else "",
            key=key,
            help=f.help,
            placeholder=f.placeholder,
        )

    if f.type == "number":
        kw: dict[str, Any] = {}
        if f.min_val is not None:
            kw["min_value"] = f.min_val
        if f.max_val is not None:
            kw["max_value"] = f.max_val
        if f.step is not None:
            kw["step"] = f.step
        val = default if default is not None else (f.min_val or 0)
        use_float = any(
            isinstance(x, float) for x in [val, f.min_val, f.max_val, f.step] if x is not None
        )
        if use_float:
            val = float(val)
            kw = {k: float(v) for k, v in kw.items()}
        else:
            val = int(val)
        return st.number_input(label, value=val, key=key, help=f.help, **kw)

    if f.type == "date":
        if default:
            try:
                d = date.fromisoformat(str(default))
            except ValueError:
                d = date.today()
        else:
            d = date.today()
        return st.date_input(label, value=d, key=key, help=f.help)

    if f.type == "select":
        opts = f.options or []
        idx = opts.index(default) if default in opts else 0
        val = st.selectbox(label, opts, index=idx, key=key, help=f.help)
        return val if val else None

    if f.type == "multiselect":
        sel = default if isinstance(default, list) else ([] if default is None else [default])
        return st.multiselect(label, f.options or [], default=sel, key=key, help=f.help)

    if f.type == "checkbox":
        return st.checkbox(label, value=bool(default), key=key, help=f.help)

    if f.type == "path":
        return st.text_input(
            label,
            value=str(default) if default else "",
            key=key,
            help=f.help,
            placeholder="/path/to/file",
        )

    return st.text_input(label, value=str(default) if default else "", key=key)


def render_form(
    spec: CommandSpec, prefix: str = "", defaults: dict | None = None, columns: int = 2
) -> dict:
    """
    依 CommandSpec.fields 自動渲染整個表單。

    回傳 {field_name: value} dict（僅包含非空值）。
    """
    if defaults is None:
        defaults = {}
    params: dict[str, Any] = {}

    required_fields = [f for f in spec.fields if f.required]
    optional_fields = [f for f in spec.fields if not f.required]

    # 必填欄位
    if required_fields:
        if len(required_fields) > 1:
            req_cols = st.columns(min(len(required_fields), columns))
            for i, f in enumerate(required_fields):
                with req_cols[i % len(req_cols)]:
                    val = _render_field(f, prefix, defaults)
                    if val is not None and val != "" and val != []:
                        params[f.name] = val
        else:
            val = _render_field(required_fields[0], prefix, defaults)
            if val is not None and val != "" and val != []:
                params[required_fields[0].name] = val

    # 選填欄位（可折疊）
    if optional_fields:
        with st.expander("進階選項", expanded=False):
            opt_cols = st.columns(columns)
            for i, f in enumerate(optional_fields):
                with opt_cols[i % columns]:
                    val = _render_field(f, prefix, defaults)
                    if f.type == "checkbox":
                        if val:
                            params[f.name] = val
                    elif f.type == "multiselect":
                        if val:
                            params[f.name] = val
                    elif f.type == "select":
                        if val:
                            params[f.name] = val
                    elif val is not None and val != "":
                        params[f.name] = val

    return params
