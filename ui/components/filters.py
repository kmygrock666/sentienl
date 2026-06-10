from __future__ import annotations

from datetime import date
from typing import Optional

import streamlit as st
from sqlalchemy.engine import Engine

from ui.services.queries import get_available_scan_dates, get_available_strategies


def market_selector(key: str = "market") -> str:
    return st.selectbox(
        "市場", ["", "TWSE", "TPEX"], key=key, format_func=lambda x: "全部" if x == "" else x
    )


def strategy_selector(engine: Engine, key: str = "strategy") -> Optional[str]:
    strategies = get_available_strategies(engine)
    options = [""] + strategies
    return (
        st.selectbox(
            "策略",
            options,
            key=key,
            format_func=lambda x: "全部" if x == "" else x,
        )
        or None
    )


def scan_date_selector(engine: Engine, key: str = "scan_date") -> Optional[date]:
    dates = get_available_scan_dates(engine)
    if not dates:
        st.info("尚無掃描結果資料")
        return None
    return st.selectbox("掃描日期", dates, key=key, format_func=lambda d: str(d))


def date_range_selector(key_prefix: str = "dr") -> tuple[date, date]:
    col1, col2 = st.columns(2)
    from datetime import timedelta

    default_end = date.today()
    default_start = default_end - timedelta(days=365)
    start = col1.date_input("開始日期", value=default_start, key=f"{key_prefix}_start")
    end = col2.date_input("結束日期", value=default_end, key=f"{key_prefix}_end")
    return start, end
