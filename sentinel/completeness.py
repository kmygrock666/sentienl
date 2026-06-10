from __future__ import annotations

from typing import Dict, Iterable

import pandas as pd


def build_run_completeness_summary(
    universe_prices: pd.DataFrame,
    valid_prices: pd.DataFrame,
    invalid_prices: pd.DataFrame,
    trading_calendar: pd.DataFrame,
    markets: Iterable[str],
    stock_master: pd.DataFrame | None = None,
) -> Dict[str, object]:
    normalized_markets = [str(market).upper() for market in markets]
    trading_days = trading_calendar[
        trading_calendar["exchange"].isin(normalized_markets)
        & trading_calendar["is_trading_day"].eq(True)
    ].copy()
    trading_days["exchange"] = trading_days["exchange"].astype(str).str.upper()

    basis = "known_symbols_in_local_dataset"
    if stock_master is not None and not stock_master.empty:
        market_universe = stock_master[["market", "symbol", "list_status"]].copy()
        market_universe["market"] = market_universe["market"].astype(str).str.upper()
        market_universe["symbol"] = market_universe["symbol"].astype(str).str.strip()
        market_universe["list_status"] = (
            market_universe["list_status"].astype(str).str.lower().str.strip()
        )
        market_universe = market_universe[market_universe["list_status"] == "active"][
            ["market", "symbol"]
        ].drop_duplicates()
        basis = "active_stocks_master"
    elif universe_prices.empty:
        market_universe = pd.DataFrame(columns=["market", "symbol"])
    else:
        market_universe = universe_prices[["market", "symbol"]].copy()
        market_universe["market"] = market_universe["market"].astype(str).str.upper()
        market_universe["symbol"] = market_universe["symbol"].astype(str).str.strip()
        market_universe = market_universe.drop_duplicates()

    market_rows = []
    total_expected = 0
    total_actual = 0
    total_quarantined = 0

    for market in normalized_markets:
        trading_day_count = int(
            trading_days.loc[trading_days["exchange"] == market, "calendar_date"].nunique()
        )
        symbol_count = int(
            market_universe.loc[market_universe["market"] == market, "symbol"].nunique()
        )
        expected_rows = symbol_count * trading_day_count
        market_symbols = set(
            market_universe.loc[market_universe["market"] == market, "symbol"].tolist()
        )
        valid_market_data = valid_prices[valid_prices["market"].astype(str).str.upper() == market]
        actual_rows = int(
            valid_market_data[valid_market_data["symbol"].isin(market_symbols)].shape[0]
        )
        quarantined_rows = int(
            invalid_prices.loc[invalid_prices["market"].astype(str).str.upper() == market].shape[0]
        )
        completeness_pct = round(actual_rows / expected_rows, 6) if expected_rows > 0 else None

        total_expected += expected_rows
        total_actual += actual_rows
        total_quarantined += quarantined_rows
        market_rows.append(
            {
                "market": market,
                "known_symbols": symbol_count,
                "trading_days": trading_day_count,
                "expected_rows": expected_rows,
                "actual_rows": actual_rows,
                "quarantined_rows": quarantined_rows,
                "completeness_pct": completeness_pct,
            }
        )

    total_completeness_pct = round(total_actual / total_expected, 6) if total_expected > 0 else None
    return {
        "basis": basis,
        "expected_rows": total_expected,
        "actual_rows": total_actual,
        "quarantined_rows": total_quarantined,
        "completeness_pct": total_completeness_pct,
        "by_market": market_rows,
    }
