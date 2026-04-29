from __future__ import annotations

from datetime import date, timedelta

import pandas as pd

from sentinel.calendar import save_trading_calendar
from sentinel.pipeline import compute_indicators, save_results, scan_strategy


def build_sample_prices(days: int = 25) -> pd.DataFrame:
    base_date = date(2026, 1, 1)
    records = []
    for offset in range(days):
        trading_date = base_date + timedelta(days=offset)
        records.append(
            {
                "symbol": "2330",
                "name": "TSMC",
                "market": "TWSE",
                "trading_date": trading_date,
                "open": 100.0 + offset,
                "high": 101.0 + offset,
                "low": 99.0 + offset,
                "close": 100.0 + offset,
                "volume": 1000 + offset,
                "turnover": 100000 + offset,
                "source": "fixture",
            }
        )
    return pd.DataFrame.from_records(records)


def test_compute_indicators_adds_ma_columns() -> None:
    prices = build_sample_prices()

    enriched = compute_indicators(prices)

    latest_row = enriched.iloc[-1]
    assert round(latest_row["ma5"], 4) == 122.0
    assert round(latest_row["ma20"], 4) == 114.5
    assert round(latest_row["volume_ma5"], 4) == 1022.0
    assert round(latest_row["atr14"], 4) == 2.0
    assert round(latest_row["bb_middle_20"], 4) == 114.5
    assert round(latest_row["rsi14"], 4) == 100.0


def test_scan_strategy_filters_latest_trading_date() -> None:
    prices = build_sample_prices()
    enriched = compute_indicators(prices)

    result = scan_strategy(enriched, trading_date=date(2026, 1, 25))

    assert list(result["symbol"]) == ["2330"]
    assert result.iloc[0]["signal"] == "mvp_ma_crossover"


def test_save_results_writes_metadata_and_rows(tmp_path) -> None:
    results = pd.DataFrame(
        [
            {
                "symbol": "2330",
                "name": "TSMC",
                "market": "TWSE",
                "trading_date": date(2026, 1, 25),
                "close": 124.0,
                "ma5": 122.0,
                "ma20": 114.5,
                "signal": "close_gt_ma5_and_ma5_gt_ma20",
            }
        ]
    )

    artifacts = save_results(
        scan_results=results,
        output_dir=tmp_path,
        run_id="run-1",
        trading_date=date(2026, 1, 25),
        data_version="v1",
    )

    assert artifacts["csv"].exists()
    assert artifacts["json"].exists()
    assert artifacts["metadata"].exists()


def test_save_trading_calendar_writes_csv_and_json(tmp_path) -> None:
    calendar_frame = pd.DataFrame(
        [
            {
                "exchange": "TWSE",
                "calendar_date": date(2026, 1, 23),
                "is_trading_day": False,
                "reason": "Holiday",
            }
        ]
    )

    artifacts = save_trading_calendar(
        trading_calendar=calendar_frame,
        output_dir=tmp_path,
        start_date=date(2026, 1, 23),
        end_date=date(2026, 1, 23),
    )

    assert artifacts["csv"].exists()
    assert artifacts["json"].exists()
