from __future__ import annotations

from datetime import date

import pandas as pd

from sentinel.storage import load_price_dataset, upsert_prices


def test_upsert_prices_keeps_latest_row_per_key() -> None:
    existing = pd.DataFrame(
        [
            {
                "symbol": "2330",
                "name": "TSMC",
                "market": "TWSE",
                "trading_date": date(2026, 1, 25),
                "open": 100.0,
                "high": 105.0,
                "low": 99.0,
                "close": 101.0,
                "volume": 1000,
                "turnover": 100000,
                "source": "old",
            }
        ]
    )
    incoming = pd.DataFrame(
        [
            {
                "symbol": "2330",
                "name": "TSMC",
                "market": "TWSE",
                "trading_date": date(2026, 1, 25),
                "open": 101.0,
                "high": 106.0,
                "low": 100.0,
                "close": 102.0,
                "volume": 1200,
                "turnover": 120000,
                "source": "new",
            }
        ]
    )

    merged = upsert_prices(existing, incoming)

    assert len(merged.index) == 1
    assert merged.iloc[0]["close"] == 102.0
    assert merged.iloc[0]["source"] == "new"


def test_upsert_prices_normalizes_symbol_types_before_dedup() -> None:
    existing = pd.DataFrame(
        [
            {
                "symbol": 2330,
                "name": "TSMC",
                "market": "twse",
                "trading_date": date(2026, 1, 25),
                "open": 100.0,
                "high": 105.0,
                "low": 99.0,
                "close": 101.0,
                "volume": 1000,
                "turnover": 100000,
                "source": "old",
            }
        ]
    )
    incoming = pd.DataFrame(
        [
            {
                "symbol": "2330",
                "name": "TSMC",
                "market": "TWSE",
                "trading_date": date(2026, 1, 25),
                "open": 101.0,
                "high": 106.0,
                "low": 100.0,
                "close": 102.0,
                "volume": 1200,
                "turnover": 120000,
                "source": "new",
            }
        ]
    )

    merged = upsert_prices(existing, incoming)

    assert len(merged.index) == 1
    assert merged.iloc[0]["symbol"] == "2330"
    assert merged.iloc[0]["market"] == "TWSE"
    assert merged.iloc[0]["close"] == 102.0


def test_load_price_dataset_reads_symbol_as_string(tmp_path) -> None:
    dataset_path = tmp_path / "daily_prices.csv"
    dataset_path.write_text(
        "\n".join(
            [
                "symbol,name,market,trading_date,open,high,low,close,volume,turnover,source",
                "2330,TSMC,TWSE,2026-01-25,100,105,99,101,1000,100000,fixture",
            ]
        ),
        encoding="utf-8",
    )

    loaded = load_price_dataset(dataset_path)

    assert loaded.iloc[0]["symbol"] == "2330"
    assert loaded.iloc[0]["market"] == "TWSE"
