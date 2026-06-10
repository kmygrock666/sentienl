from __future__ import annotations

import pandas as pd
import streamlit as st

_STATUS_COLORS = {
    "running": "🟡",
    "success": "🟢",
    "failed": "🔴",
    "error": "🔴",
    "pending": "⚪",
}


def status_badge(status: str) -> str:
    icon = _STATUS_COLORS.get(status.lower(), "⚪")
    return f"{icon} {status}"


def render_job_runs(df: pd.DataFrame) -> None:
    if df.empty:
        st.info("尚無 Job 記錄")
        return
    display = df.copy()
    display["status"] = display["status"].apply(status_badge)
    display["duration"] = (
        (pd.to_datetime(display["end_time"]) - pd.to_datetime(display["start_time"]))
        .dt.total_seconds()
        .apply(lambda s: f"{s:.0f}s" if pd.notna(s) else "—")
    )
    st.dataframe(
        display[
            ["job_name", "status", "start_time", "duration", "rows_in", "rows_out", "error_summary"]
        ],
        width="stretch",
        hide_index=True,
    )


def render_scan_results(df: pd.DataFrame) -> pd.DataFrame:
    """Render scan results table. Returns the row the user clicks (via selection)."""
    if df.empty:
        st.info("此條件無結果")
        return pd.DataFrame()
    display = df[
        ["trading_date", "market", "symbol", "name", "industry", "strategy_id", "score", "close"]
    ].copy()
    display["score"] = display["score"].apply(lambda x: f"{x:.4f}" if x is not None else "—")
    display["close"] = display["close"].apply(lambda x: f"{x:.2f}" if x is not None else "—")

    event = st.dataframe(
        display,
        width="stretch",
        hide_index=True,
        on_select="rerun",
        selection_mode="single-row",
    )
    selected_rows = event.selection.get("rows", []) if event and event.selection else []
    if selected_rows:
        return df.iloc[selected_rows]
    return pd.DataFrame()
