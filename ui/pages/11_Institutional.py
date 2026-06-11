"""主力買賣超 — 三大法人買賣超排行頁面。

子頁籤：外資 | 投信 | 自營商 | 三大法人 | 外資連買榜
"""

from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent.parent))

from datetime import date

import pandas as pd
import streamlit as st

from ui.components.layout import inject_css, section_header
from ui.services.db import get_engine
from ui.services.queries import (
    get_foreign_streak_ranking,
    get_institutional_dates,
    get_institutional_ranking,
)

st.set_page_config(page_title="Institutional | Sentinel", layout="wide")
inject_css()
st.title("💰 主力買賣超")
st.caption("三大法人買賣超排行（資料來源：sync-institutional）")

# 台股慣例：買超紅、賣超綠；琥珀為強調色
_UP = "#E5484D"
_DOWN = "#2FA46C"
_AMBER = "#F0A03C"
_STREAK_HIGHLIGHT_DAYS = 5

# ── 資料庫與可用日期 ─────────────────────────────────────────────────────────
try:
    engine = get_engine()
except Exception as e:
    st.error(f"資料庫連線失敗：{e}")
    st.stop()

try:
    available_dates = get_institutional_dates(engine)
except Exception as e:
    st.error(f"讀取法人資料日期失敗：{e}")
    st.stop()

if not available_dates:
    st.info("尚無法人買賣超資料，請先至 Data Sync 頁面執行 sync-institutional")
    st.page_link("pages/2_Data_Sync.py", label="🔄 前往 Data Sync", use_container_width=False)
    st.stop()

# ── 控制列 ──────────────────────────────────────────────────────────────────
c1, c2, c3 = st.columns(3)
sel_date = c1.selectbox("日期", [str(d) for d in available_dates], index=0)
sel_market = c2.selectbox("市場", ["全部", "TWSE", "TPEX"])
top_n = c3.number_input("Top N", min_value=10, max_value=50, value=20, step=5)

query_date = date.fromisoformat(sel_date)
query_market = sel_market if sel_market != "全部" else None


# ── 樣式工具 ────────────────────────────────────────────────────────────────
def _net_color(value: int) -> str:
    """買賣超欄位顏色：正紅、負綠（台股慣例）。"""
    if pd.isna(value):
        return ""
    if value > 0:
        return f"color: {_UP}"
    if value < 0:
        return f"color: {_DOWN}"
    return ""


def _streak_color(value: int) -> str:
    """連買天數 >= 5 以琥珀色強調。"""
    if pd.notna(value) and value >= _STREAK_HIGHLIGHT_DAYS:
        return f"color: {_AMBER}; font-weight: 600"
    return ""


def _render_ranking_table(net_column: str, ascending: bool) -> None:
    """渲染單側（買超或賣超）排行表。"""
    try:
        df = get_institutional_ranking(
            engine,
            query_date,
            net_column,
            market=query_market,
            ascending=ascending,
            limit=int(top_n),
        )
    except Exception as e:
        st.error(f"查詢排行失敗：{e}")
        return
    if df.empty:
        st.info("此條件下無資料")
        return
    styled = df.style.map(_net_color, subset=["買賣超(張)"]).format({"買賣超(張)": "{:,}"})
    st.dataframe(styled, use_container_width=True, hide_index=True)


def _render_ranking_tab(net_column: str) -> None:
    """單一法人別頁籤：左買超 / 右賣超。"""
    left, right = st.columns(2)
    with left:
        section_header(f"買超 Top {int(top_n)}")
        _render_ranking_table(net_column, ascending=False)
    with right:
        section_header(f"賣超 Top {int(top_n)}")
        _render_ranking_table(net_column, ascending=True)


# ── 頁籤 ────────────────────────────────────────────────────────────────────
tab_specs = [
    ("外資", "foreign_net"),
    ("投信", "investment_trust_net"),
    ("自營商", "dealer_net"),
    ("三大法人", "total_net"),
]
tabs = st.tabs([label for label, _ in tab_specs] + ["🔥 外資連買榜"])

for tab, (_, net_column) in zip(tabs, tab_specs):
    with tab:
        _render_ranking_tab(net_column)

with tabs[-1]:
    section_header("外資連買榜", f"以 {sel_date} 往回 10 個資料日計算")
    st.caption(
        "連買天數：從所選日期往回、外資買超（>0）連續的資料日天數，"
        "中斷或缺資料即停止計算；僅列出連買 2 天以上者。期間累計為連買期間的買超加總（張）。"
    )
    try:
        streak_df = get_foreign_streak_ranking(
            engine, query_date, market=query_market, limit=int(top_n)
        )
    except Exception as e:
        st.error(f"查詢連買榜失敗：{e}")
        streak_df = pd.DataFrame()
    if streak_df.empty:
        st.info("此條件下無連買 2 天以上的個股（資料日不足時屬正常）")
    else:
        styled_streak = (
            streak_df.style.map(_streak_color, subset=["連買天數"])
            .map(_net_color, subset=["期間累計(張)"])
            .format({"期間累計(張)": "{:,}"})
        )
        st.dataframe(styled_streak, use_container_width=True, hide_index=True)

# ── 底部導引 ────────────────────────────────────────────────────────────────
st.divider()
st.caption("想看個股的法人進出明細？前往 Stock Check 輸入代號查詢。")
st.page_link("pages/4_Stock_Check.py", label="📈 前往 Stock Check 查詢個股明細")
