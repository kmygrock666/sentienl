"""UI 查詢入口：Streamlit 快取包裝＋轉出口 sentinel.storage.repositories。

SQL 一律住在 sentinel/storage/repositories/；本模組只保留
需要 Streamlit 快取的 CSV dataset 讀取，並轉出口 repository 函式
讓既有頁面的 `from ui.services.queries import ...` 匯入路徑維持不變。
"""

from __future__ import annotations

from pathlib import Path as _Path

import pandas as pd
import streamlit as st

from sentinel.config import Settings
from sentinel.storage import load_price_dataset
from sentinel.storage.repositories import (
    get_available_scan_dates,
    get_available_strategies,
    get_daily_prices,
    get_data_freshness,
    get_foreign_streak_ranking,
    get_indicators,
    get_institutional_dates,
    get_institutional_flow,
    get_institutional_ranking,
    get_intraday_trades,
    get_latest_institutional_date,
    get_latest_job_runs,
    get_latest_main_force_dates,
    get_latest_price_date,
    get_latest_scan_summary,
    get_main_force_daily,
    get_quarantine_summary,
    get_scan_results,
    get_stock_scan_history,
)

__all__ = [
    "get_available_scan_dates",
    "get_available_strategies",
    "get_daily_prices",
    "get_data_freshness",
    "get_foreign_streak_ranking",
    "get_indicators",
    "get_institutional_dates",
    "get_institutional_flow",
    "get_institutional_ranking",
    "get_intraday_trades",
    "get_latest_institutional_date",
    "get_latest_job_runs",
    "get_latest_main_force_dates",
    "get_latest_price_date",
    "get_latest_scan_summary",
    "get_main_force_daily",
    "get_quarantine_summary",
    "get_scan_results",
    "get_stock_scan_history",
    "load_symbol_prices",
]


@st.cache_resource
def _cached_price_dataset(dataset_path: str) -> pd.DataFrame:
    """Load full price CSV once and hold in memory across all page navigations.

    以路徑作為快取鍵：路徑（設定）改變時會重新載入，而非沿用舊資料。
    """
    return load_price_dataset(_Path(dataset_path))


_PRICE_FRAME_COLUMNS = [
    "market",
    "symbol",
    "trading_date",
    "open",
    "high",
    "low",
    "close",
    "volume",
]


def load_symbol_prices(symbol: str, days: int = 120, market: str | None = None) -> pd.DataFrame:
    """從 CSV 價格資料集載入單一個股最近 N 個交易日（昇冪）。找不到回空 frame。

    Args:
        symbol: 股票代號（字串比對）。
        days:   最多取最近幾個交易日，預設 120。
        market: 若指定（"TWSE" 或 "TPEX"），只回傳該市場的列；
                None 則不過濾市場（注意：相同代號可能同時出現在 TWSE 與
                TPEX，會造成 (symbol, trading_date) 重複，呼叫端應傳入
                market 以避免碰撞）。
    """
    dataset = _cached_price_dataset(str(Settings().price_dataset_path))
    if dataset.empty:
        return pd.DataFrame(columns=_PRICE_FRAME_COLUMNS)
    matched = dataset.loc[dataset["symbol"].astype(str) == symbol]
    if market is not None:
        matched = matched.loc[matched["market"] == market]
    if matched.empty:
        return pd.DataFrame(columns=_PRICE_FRAME_COLUMNS)
    return matched.sort_values("trading_date").tail(days).reset_index(drop=True)
