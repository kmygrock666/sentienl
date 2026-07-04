"""法人籌碼 widget：連買天數、籌碼 K 線圖與近日買賣超明細。"""

from __future__ import annotations

from typing import Optional, Tuple

import pandas as pd
import streamlit as st

from ui.components.charts import candlestick_with_institutional
from ui.components.stock_check.summary import foreign_buy_streak
from ui.services.queries import get_institutional_flow, load_symbol_prices

_MARKETS = ("TWSE", "TPEX")


def resolve_market(engine, symbol: str) -> Optional[str]:
    """由股票主檔判斷個股市場；查無回傳 None。"""
    try:
        from sqlalchemy.orm import Session

        from sentinel.domain.models import Stock

        with Session(engine) as s:
            for market in _MARKETS:
                found = (
                    s.query(Stock.symbol)
                    .filter(Stock.market == market, Stock.symbol == symbol)
                    .first()
                )
                if found:
                    return market
    except Exception:
        pass
    return None


def fetch_flow(engine, symbol: str) -> Tuple[Optional[str], Optional[pd.DataFrame]]:
    """依市場探測法人買賣超；回傳 (market, flow_df)，皆可為 None。"""
    for market in _MARKETS:
        df = get_institutional_flow(engine, market, symbol)
        if not df.empty:
            return market, df
    return None, None


def render_institutional_panel(
    engine,
    symbol: str,
    *,
    market: Optional[str] = None,
    flow_df: Optional[pd.DataFrame] = None,
    title: str = "",
) -> None:
    """法人籌碼面板：連買指標＋籌碼 K 線＋近 10 日明細表。

    market / flow_df 可由呼叫端預先查好傳入（避免重複查詢）。
    """
    if flow_df is None:
        market, flow_df = fetch_flow(engine, symbol)

    if flow_df is None or flow_df.empty:
        st.info("尚無法人籌碼資料，請先至 Data Sync 執行 sync-institutional")
        return

    streak = foreign_buy_streak(flow_df)
    st.metric("外資連續買超天數", f"{streak} 天")

    resolved_market = market or resolve_market(engine, symbol)
    price_df = load_symbol_prices(symbol, days=120, market=resolved_market)
    if not price_df.empty:
        fig = candlestick_with_institutional(price_df, flow_df, title=title or symbol)
        st.plotly_chart(fig, use_container_width=True)

    st.markdown("**近 10 個交易日買賣超（張）**")
    st.dataframe(flow_df, width="stretch", hide_index=True)
