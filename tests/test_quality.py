from __future__ import annotations

from datetime import date

import pandas as pd

from sentinel.quality import (
    RULE_HIGH_GTE_MAX_OPEN_CLOSE,
    RULE_LOW_LTE_MIN_OPEN_CLOSE,
    RULE_VOLUME_NON_NEGATIVE,
    VALIDITY_RULE,
    validate_daily_prices,
)


def test_validate_daily_prices_splits_valid_and_invalid_rows() -> None:
    prices = pd.DataFrame(
        [
            {
                "symbol": "2330",
                "name": "TSMC",
                "market": "TWSE",
                "trading_date": date(2026, 1, 22),
                "open": 100.0,
                "high": 105.0,
                "low": 99.0,
                "close": 101.0,
                "volume": 1000,
                "turnover": 100000,
                "source": "fixture",
            },
            {
                "symbol": "2317",
                "name": "Hon Hai",
                "market": "TWSE",
                "trading_date": date(2026, 1, 22),
                "open": 100.0,
                "high": 99.0,
                "low": 101.0,
                "close": 102.0,
                "volume": -1,
                "turnover": 100000,
                "source": "fixture",
            },
        ]
    )

    result = validate_daily_prices(prices)

    assert len(result.valid_prices.index) == 1
    assert result.valid_prices.iloc[0]["symbol"] == "2330"
    assert len(result.invalid_prices.index) == 1
    assert result.invalid_prices.iloc[0]["symbol"] == "2317"
    assert result.invalid_prices.iloc[0]["violated_rule"] == VALIDITY_RULE
    assert result.invalid_prices.iloc[0]["violations"] == [
        RULE_HIGH_GTE_MAX_OPEN_CLOSE,
        RULE_LOW_LTE_MIN_OPEN_CLOSE,
        RULE_VOLUME_NON_NEGATIVE,
    ]
