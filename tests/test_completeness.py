from __future__ import annotations

from datetime import date

import pandas as pd

from sentinel.analysis.completeness import build_run_completeness_summary


def test_build_run_completeness_summary_counts_expected_actual_and_quarantine() -> None:
    universe_prices = pd.DataFrame(
        [
            {"market": "TWSE", "symbol": "2330"},
            {"market": "TWSE", "symbol": "2317"},
            {"market": "TPEX", "symbol": "8069"},
        ]
    )
    valid_prices = pd.DataFrame(
        [
            {"market": "TWSE", "symbol": "2330", "trading_date": date(2026, 1, 22)},
            {"market": "TPEX", "symbol": "8069", "trading_date": date(2026, 1, 22)},
        ]
    )
    invalid_prices = pd.DataFrame(
        [
            {"market": "TWSE", "symbol": "2317", "trading_date": date(2026, 1, 22)},
        ]
    )
    trading_calendar = pd.DataFrame(
        [
            {
                "exchange": "TWSE",
                "calendar_date": date(2026, 1, 22),
                "is_trading_day": True,
                "reason": None,
            },
            {
                "exchange": "TPEX",
                "calendar_date": date(2026, 1, 22),
                "is_trading_day": True,
                "reason": None,
            },
        ]
    )

    summary = build_run_completeness_summary(
        universe_prices=universe_prices,
        valid_prices=valid_prices,
        invalid_prices=invalid_prices,
        trading_calendar=trading_calendar,
        markets=["TWSE", "TPEX"],
    )

    assert summary["basis"] == "known_symbols_in_local_dataset"
    assert summary["expected_rows"] == 3
    assert summary["actual_rows"] == 2
    assert summary["quarantined_rows"] == 1
    assert summary["completeness_pct"] == 0.666667
    assert summary["by_market"] == [
        {
            "market": "TWSE",
            "known_symbols": 2,
            "trading_days": 1,
            "expected_rows": 2,
            "actual_rows": 1,
            "quarantined_rows": 1,
            "completeness_pct": 0.5,
        },
        {
            "market": "TPEX",
            "known_symbols": 1,
            "trading_days": 1,
            "expected_rows": 1,
            "actual_rows": 1,
            "quarantined_rows": 0,
            "completeness_pct": 1.0,
        },
    ]


def test_build_run_completeness_summary_prefers_active_stock_master() -> None:
    stock_master = pd.DataFrame(
        [
            {"market": "TWSE", "symbol": "2330", "list_status": "active"},
            {"market": "TWSE", "symbol": "2317", "list_status": "active"},
            {"market": "TWSE", "symbol": "3008", "list_status": "inactive"},
        ]
    )
    trading_calendar = pd.DataFrame(
        [
            {
                "exchange": "TWSE",
                "calendar_date": date(2026, 1, 22),
                "is_trading_day": True,
                "reason": None,
            },
        ]
    )
    summary = build_run_completeness_summary(
        universe_prices=pd.DataFrame(columns=["market", "symbol"]),
        valid_prices=pd.DataFrame(
            [{"market": "TWSE", "symbol": "2330", "trading_date": date(2026, 1, 22)}]
        ),
        invalid_prices=pd.DataFrame(columns=["market", "symbol", "trading_date"]),
        trading_calendar=trading_calendar,
        markets=["TWSE"],
        stock_master=stock_master,
    )

    assert summary["basis"] == "active_stocks_master"
    assert summary["expected_rows"] == 2
    assert summary["actual_rows"] == 1
    assert summary["completeness_pct"] == 0.5
