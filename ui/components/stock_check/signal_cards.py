"""訊號卡片 widget：篩選、排序與逐卡渲染（條件明細收在 expander）。"""

from __future__ import annotations

import html
import json
import pathlib

import streamlit as st

_SIGNALS_PATH = pathlib.Path(__file__).parents[3] / "config" / "signals.json"

FILTERS = ["全部", "只看觸發", "只看警示", "只看未觸發", "只看需盤中"]

_DIR_LABEL = {"long": "做多進場", "warning": "警示 / 出場", "intraday": "需盤中資料"}
_STATUS_CSS = {
    "triggered_long": ("border-left:3px solid #3FA66B; background:#1a2e22;", "✅", "#3FA66B"),
    "triggered_warning": ("border-left:3px solid #E0A94A; background:#2e2a1a;", "🔴", "#E0A94A"),
    "not_triggered": ("border-left:3px solid #4a5568; background:#1a1f24;", "❌", "#9AA6B2"),
    "needs_intraday": ("border-left:3px solid #3D6E8F; background:#1a222e;", "⚙️", "#3D6E8F"),
}


@st.cache_data(show_spinner=False)
def _load_signal_descriptions() -> dict[str, str]:
    """載入訊號說明 name → description。"""
    try:
        raw = json.loads(_SIGNALS_PATH.read_text(encoding="utf-8"))
        return {s["name"]: s["description"] for s in raw.get("signals", []) if s.get("description")}
    except Exception:
        return {}


def match_filter(sig: dict, flt: str) -> bool:
    if flt == "只看觸發":
        return sig["status"] == "triggered" and sig["direction"] == "long"
    if flt == "只看警示":
        return sig["status"] == "triggered" and sig["direction"] == "warning"
    if flt == "只看未觸發":
        return sig["status"] == "not_triggered"
    if flt == "只看需盤中":
        return sig["status"] == "needs_intraday"
    return True


def sort_key(sig: dict) -> int:
    """觸發做多 > 觸發警示 > 未觸發 > 需盤中。"""
    if sig["status"] == "triggered" and sig["direction"] == "long":
        return 0
    if sig["status"] == "triggered" and sig["direction"] == "warning":
        return 1
    if sig["status"] == "not_triggered":
        return 2
    return 3


def _card_key(sig: dict) -> str:
    if sig["status"] == "triggered" and sig["direction"] == "long":
        return "triggered_long"
    if sig["status"] == "triggered" and sig["direction"] == "warning":
        return "triggered_warning"
    if sig["status"] == "needs_intraday":
        return "needs_intraday"
    return "not_triggered"


def _render_card(sig: dict, descriptions: dict[str, str]) -> None:
    css, icon, color = _STATUS_CSS[_card_key(sig)]
    dir_label = _DIR_LABEL.get(sig["direction"], sig["direction"])
    cond_summary = (
        f"{sig['passed_count']}/{sig['total_count']} 條件通過" if sig["total_count"] > 0 else ""
    )

    with st.container():
        st.markdown(
            f'<div style="padding:0.6rem 0.8rem; border-radius:4px; margin-bottom:0.5rem; {css}">'
            f'<span style="font-size:1.1rem">{icon}</span> '
            f'<strong style="color:{color}">{html.escape(sig["name"])}</strong>'
            f'<span style="color:var(--text-1);font-size:0.78rem;margin-left:0.5rem">'
            f"[{html.escape(dir_label)}]</span>"
            + (
                f'<span style="color:var(--text-1);font-size:0.78rem;margin-left:0.5rem">'
                f"· {cond_summary}</span>"
                if cond_summary
                else ""
            )
            + (
                f'<span style="color:var(--text-1);font-size:0.78rem;margin-left:0.5rem">'
                f'— {html.escape(sig["source_rule"])}</span>'
                if sig.get("source_rule")
                else ""
            )
            + "</div>",
            unsafe_allow_html=True,
        )

        # Signal description（只在觸發時顯示，幫助使用者理解其功效）
        desc = descriptions.get(sig["name"], "")
        if desc and sig["status"] == "triggered":
            st.markdown(
                f'<div style="margin:0 0 0.4rem 0.8rem;color:#9AA6B2;font-size:0.80rem">'
                f"📌 {html.escape(desc)}</div>",
                unsafe_allow_html=True,
            )

        # Conditions detail (for triggered and not_triggered)
        if sig["conditions"]:
            failed = [c for c in sig["conditions"] if not c["passed"]]

            if sig["status"] == "triggered":
                with st.expander(f"條件明細（{sig['passed_count']}/{sig['total_count']} 通過）"):
                    for c in sig["conditions"]:
                        mark = "✅" if c["passed"] else "  "
                        st.markdown(
                            f'<span style="font-family:monospace;font-size:0.82rem;color:{"#3FA66B" if c["passed"] else "#9AA6B2"}">'
                            f'{mark} {html.escape(c["text"])}</span>',
                            unsafe_allow_html=True,
                        )
            elif failed:
                fail_text = "；".join(c["text"] for c in failed[:3])
                st.markdown(
                    f'<div style="margin-left:1rem;color:#9AA6B2;font-size:0.80rem">'
                    f"未達條件：{html.escape(fail_text)}"
                    + (" 等..." if len(failed) > 3 else "")
                    + "</div>",
                    unsafe_allow_html=True,
                )
                if len(sig["conditions"]) > 3:
                    with st.expander("展開全部條件"):
                        for c in sig["conditions"]:
                            mark = "✅" if c["passed"] else "✗"
                            st.markdown(
                                f'<span style="font-family:monospace;font-size:0.82rem;color:{"#3FA66B" if c["passed"] else "#D84B4B"}">'
                                f'{mark} {html.escape(c["text"])}</span>',
                                unsafe_allow_html=True,
                            )

        # Intraday reason
        if sig["status"] == "needs_intraday" and sig.get("reason"):
            st.markdown(
                f'<div style="margin-left:1rem;color:#3D6E8F;font-size:0.80rem">'
                f'原因：{html.escape(sig["reason"])}</div>',
                unsafe_allow_html=True,
            )


def render_signal_cards(signals: list[dict]) -> None:
    """篩選列＋依優先序排序的訊號卡片清單。"""
    flt = st.radio("篩選", FILTERS, horizontal=True, label_visibility="collapsed")
    visible = sorted([s for s in signals if match_filter(s, flt)], key=sort_key)

    if not visible:
        st.info("此篩選條件無符合訊號")
        return

    descriptions = _load_signal_descriptions()
    for sig in visible:
        _render_card(sig, descriptions)
