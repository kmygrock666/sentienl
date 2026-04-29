from __future__ import annotations

from datetime import date, timedelta

import pandas as pd

from sentinel.backtest import run_backtest
from sentinel.pipeline import compute_indicators
from sentinel.strategies import load_strategy_definitions, scan_strategies


def build_strategy_prices(days: int = 40) -> pd.DataFrame:
    base_date = date(2026, 1, 1)
    records = []
    for offset in range(days):
        trading_date = base_date + timedelta(days=offset)
        close = 100.0 + offset
        records.append(
            {
                "symbol": "2330",
                "name": "TSMC",
                "market": "TWSE",
                "trading_date": trading_date,
                "open": close - 0.5,
                "high": close + 1.0,
                "low": close - 1.0,
                "close": close,
                "volume": 1000 + offset,
                "turnover": 100000 + offset,
                "source": "fixture",
            }
        )
    return pd.DataFrame.from_records(records)


def test_load_strategy_definitions_uses_repo_defaults() -> None:
    strategies = load_strategy_definitions()

    assert len(strategies) >= 3
    assert {strategy["strategy_id"] for strategy in strategies} >= {
        "mvp_ma_crossover",
        "rsi_pullback",
        "volume_breakout",
    }


def test_scan_strategies_returns_multiple_strategy_results() -> None:
    prices = build_strategy_prices()
    enriched = compute_indicators(prices)
    strategies = load_strategy_definitions()

    result = scan_strategies(enriched, trading_date=date(2026, 2, 9), strategies=strategies)

    assert "mvp_ma_crossover" in set(result["strategy_id"])
    assert all(result["signals_json"].map(lambda payload: "conditions" in payload))


def test_run_backtest_generates_report_and_trades() -> None:
    prices = build_strategy_prices(days=50)
    enriched = compute_indicators(prices)
    strategies = [strategy for strategy in load_strategy_definitions() if strategy["strategy_id"] == "mvp_ma_crossover"]

    reports, trades = run_backtest(
        prices_with_indicators=enriched,
        strategies=strategies,
        start_date=date(2026, 1, 20),
        end_date=date(2026, 2, 10),
        benchmark_symbol="2330",
    )

    assert len(reports.index) == 1
    assert len(trades.index) > 0
    assert reports.iloc[0]["strategy_id"] == "mvp_ma_crossover"
    assert reports.iloc[0]["benchmark_total_return"] is not None
