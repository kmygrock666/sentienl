from __future__ import annotations

from datetime import date

import pandas as pd

from sentinel.quality import (
    RULE_HIGH_GTE_MAX_OPEN_CLOSE,
    RULE_LOW_LTE_MIN_OPEN_CLOSE,
    RULE_PRICE_CHANGE_SPIKE,
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


def test_spike_uses_most_recent_prior_close_within_batch() -> None:
    """同批次內跨日比較：第二天的漲幅應以第一天收盤為基準。"""
    prices = pd.DataFrame(
        [
            {
                "market": "TWSE",
                "symbol": "2330",
                "trading_date": "2026-03-02",
                "open": 100,
                "high": 101,
                "low": 99,
                "close": 100,
                "volume": 1000,
                "turnover": 1,
            },
            {
                "market": "TWSE",
                "symbol": "2330",
                "trading_date": "2026-03-03",
                "open": 100,
                "high": 130,
                "low": 99,
                "close": 130,
                "volume": 1000,
                "turnover": 1,
            },
            # 多檔正常股，避免觸發 bulk-anomaly guard（>15% 同日清旗標）
            *[
                {
                    "market": "TWSE",
                    "symbol": f"11{i:02d}",
                    "trading_date": "2026-03-03",
                    "open": 50,
                    "high": 51,
                    "low": 49,
                    "close": 50,
                    "volume": 500,
                    "turnover": 1,
                }
                for i in range(10)
            ],
        ]
    )
    reference = pd.DataFrame(
        [
            {
                "market": "TWSE",
                "symbol": f"11{i:02d}",
                "trading_date": "2026-03-02",
                "open": 50,
                "high": 51,
                "low": 49,
                "close": 50,
                "volume": 500,
                "turnover": 1,
            }
            for i in range(10)
        ]
    )
    result = validate_daily_prices(prices, reference_prices=reference)
    flagged = set(result.invalid_prices["symbol"])
    assert (
        RULE_PRICE_CHANGE_SPIKE
        in result.invalid_prices.loc[result.invalid_prices["symbol"] == "2330", "violations"].iloc[
            0
        ]
    )
    assert "2330" in flagged
    assert len(flagged) == 1
