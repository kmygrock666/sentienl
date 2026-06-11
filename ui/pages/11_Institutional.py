"""主力買賣超 — 三大法人買賣超排行頁面。

子頁籤：外資 | 投信 | 自營商 | 三大法人 | 外資連買榜 | 籌碼K線
"""

from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent.parent))

from datetime import date

import pandas as pd
import streamlit as st

from ui.components.charts import candlestick_with_institutional
from ui.components.layout import inject_css, section_header
from ui.services.db import get_engine
from ui.services.queries import (
    get_foreign_streak_ranking,
    get_institutional_dates,
    get_institutional_flow,
    get_institutional_ranking,
    load_symbol_prices,
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


def _fmt_lots(value) -> str:
    """合計張數顯示：正值帶 +，缺值顯示 —。"""
    return f"{int(value):+,}" if pd.notna(value) else "—"


def _render_kline_tab() -> None:
    """籌碼K線：K線 + 成交量 + 每日法人買賣超，日期對齊。"""
    c1, c2, c3 = st.columns(3)
    symbol = (
        c1.text_input("股票代號", value=st.session_state.get("inst_kline_symbol", "2330")) or ""
    ).strip()
    kline_market = c2.selectbox("市場", ["自動", "TWSE", "TPEX"], key="inst_kline_market")
    period = c3.selectbox("期間（交易日）", [60, 120, 240], index=1, key="inst_kline_days")
    if not symbol:
        st.info("請輸入股票代號")
        return
    st.session_state["inst_kline_symbol"] = symbol

    # 價格：CSV 資料集
    try:
        price_df = load_symbol_prices(symbol, days=period)
    except Exception as e:
        st.error(f"讀取價格資料失敗：{e}")
        return
    if price_df.empty:
        st.warning(f"找不到 {symbol} 的價格資料，請先執行每日同步")
        return
    price_df = price_df.assign(trading_date=pd.to_datetime(price_df["trading_date"]))

    # 法人買賣超：自動模式先試 TWSE 再試 TPEX
    flow_df = pd.DataFrame()
    markets = ("TWSE", "TPEX") if kline_market == "自動" else (kline_market,)
    try:
        for mkt in markets:
            df = get_institutional_flow(engine, mkt, symbol, days=period)
            if not df.empty:
                flow_df = df
                break
    except Exception as e:
        st.warning(f"法人籌碼查詢失敗：{e}")

    if not flow_df.empty:
        # 圖表需昇冪；日期與價格軸統一為 datetime
        flow_df = flow_df.sort_values("日期").reset_index(drop=True)
        flow_df = flow_df.assign(日期=pd.to_datetime(flow_df["日期"]))

    fig = candlestick_with_institutional(
        price_df,
        flow_df if not flow_df.empty else None,
        title=f"{symbol} 籌碼K線",
    )
    st.plotly_chart(fig, use_container_width=True)

    if flow_df.empty:
        st.info("此股票尚無法人籌碼資料")
        return

    recent5 = flow_df.tail(5)
    m1, m2, m3 = st.columns(3)
    m1.metric("近5日外資合計(張)", _fmt_lots(recent5["外資"].sum()))
    m2.metric("近5日投信合計(張)", _fmt_lots(recent5["投信"].sum()))
    m3.metric("近5日自營商合計(張)", _fmt_lots(recent5["自營商"].sum()))

    section_header("近 10 個交易日明細", "單位：張")
    recent10 = flow_df.tail(10).sort_values("日期", ascending=False)
    net_cols = ["外資", "投信", "自營商", "合計"]
    fmt: dict = {c: "{:,}" for c in net_cols}
    fmt["日期"] = "{:%Y-%m-%d}"
    styled = recent10.style.map(_net_color, subset=net_cols).format(fmt, na_rep="—")
    st.dataframe(styled, use_container_width=True, hide_index=True)


# ── 頁籤 ────────────────────────────────────────────────────────────────────
tab_specs = [
    ("外資", "foreign_net"),
    ("投信", "investment_trust_net"),
    ("自營商", "dealer_net"),
    ("三大法人", "total_net"),
]
tabs = st.tabs([label for label, _ in tab_specs] + ["🔥 外資連買榜", "📈 籌碼K線"])

for tab, (_, net_column) in zip(tabs, tab_specs):
    with tab:
        _render_ranking_tab(net_column)

with tabs[-1]:
    _render_kline_tab()

with tabs[-2]:
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
