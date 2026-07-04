"""資料庫讀取 repository：所有跨介面（UI/CLI）的查詢 SQL 集中於此。

每個模組對應一個資料域；函式一律接受 Engine、回傳 DataFrame 或基本型別，
不得 import streamlit 或任何介面層元件。
"""

from sentinel.storage.repositories.indicators import get_indicators
from sentinel.storage.repositories.institutional import (
    get_foreign_streak_ranking,
    get_institutional_dates,
    get_institutional_flow,
    get_institutional_ranking,
    get_latest_institutional_date,
)
from sentinel.storage.repositories.intraday_trades import get_intraday_trades
from sentinel.storage.repositories.jobs import get_latest_job_runs
from sentinel.storage.repositories.main_force import (
    get_latest_main_force_dates,
    get_main_force_daily,
)
from sentinel.storage.repositories.prices import (
    get_daily_prices,
    get_data_freshness,
    get_latest_price_date,
)
from sentinel.storage.repositories.quarantine import get_quarantine_summary
from sentinel.storage.repositories.scans import (
    get_available_scan_dates,
    get_available_strategies,
    get_latest_scan_summary,
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
]
