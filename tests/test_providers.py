from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from sentinel.datasources.providers import TpexDailyPriceProvider, TwseDailyPriceProvider

_TWSE_PAYLOAD = """
"114年03月05日 每日收盤行情(全部(不含權證、牛熊證))"
"證券代號","證券名稱","成交股數","成交筆數","成交金額","開盤價","最高價","最低價","收盤價","漲跌(+/-)","漲跌價差","最後揭示買價","最後揭示買量","最後揭示賣價","最後揭示賣量","本益比"
"1101","台泥","12,345,678","5,678","500,000,000","32.10","32.50","31.90","32.30","+","0.20","32.25","10","32.30","20","18.5"
"1102","亞泥","7,654,321","4,321","300,000,000","41.00","41.30","40.50","41.20","+","0.10","41.15","5","41.20","8","15.2"
"""

_TPEX_PAYLOAD = """
"資料日期:114/03/05"
"代號","名稱","收盤 ","漲跌","開盤 ","最高 ","最低 ","成交股數","成交金額","成交筆數"
"8069","元太","250.50","+1.50","249.00","252.00","248.50","3,210,000","804,000,000","4,567"
"6488","環球晶","3,650.00","+20.00","3,620.00","3,680.00","3,610.00","120,000","438,000,000","980"
"""


def test_twse_parser_extracts_price_rows() -> None:
    provider = TwseDailyPriceProvider()

    frame = provider._parse_csv(_TWSE_PAYLOAD, trading_date=date(2025, 3, 5))

    assert list(frame["symbol"]) == ["1101", "1102"]
    assert frame.iloc[0]["market"] == "TWSE"
    assert frame.iloc[0]["trading_date"] == date(2025, 3, 5)
    assert frame.iloc[0]["close"] == 32.30
    assert frame.iloc[0]["turnover"] == 500000000
    assert frame.iloc[1]["volume"] == 7654321


def test_twse_parser_rejects_mismatched_date() -> None:
    provider = TwseDailyPriceProvider()

    frame = provider._parse_csv(_TWSE_PAYLOAD, trading_date=date(2026, 3, 5))

    assert frame.empty


def test_tpex_parser_extracts_price_rows() -> None:
    provider = TpexDailyPriceProvider()

    frame = provider._parse_csv(_TPEX_PAYLOAD, trading_date=date(2025, 3, 5))

    assert list(frame["symbol"]) == ["8069", "6488"]
    assert frame.iloc[0]["market"] == "TPEX"
    assert frame.iloc[0]["close"] == 250.50
    assert frame.iloc[1]["volume"] == 120000


def test_tpex_parser_rejects_mismatched_date() -> None:
    provider = TpexDailyPriceProvider()

    frame = provider._parse_csv(_TPEX_PAYLOAD, trading_date=date(2026, 3, 5))

    assert frame.empty


def test_fetch_csv_with_retry_recovers_after_failures(monkeypatch) -> None:
    """前兩次網路錯誤後第三次成功，應回傳解析結果並重試對應次數。"""
    import requests as _requests

    from sentinel.config import Settings
    from sentinel.datasources import providers as providers_module

    calls = {"n": 0}

    def fake_fetch_text(url, *, params=None, headers=None, timeout_seconds=0):
        calls["n"] += 1
        if calls["n"] < 3:
            raise _requests.RequestException("boom")
        return "payload"

    monkeypatch.setattr(providers_module, "fetch_text", fake_fetch_text)
    monkeypatch.setattr(providers_module.time, "sleep", lambda _s: None)

    settings = Settings(
        _env_file=None,
        max_retries=3,
        retry_backoff_seconds=0,
        retry_jitter_seconds=0,
        min_delay_seconds=0,
        max_delay_seconds=0,
    )
    frame = providers_module.fetch_csv_with_retry(
        endpoint="https://example.test/csv",
        params={},
        headers={},
        settings=settings,
        market="TWSE",
        trading_date=date(2025, 3, 5),
        parse_fn=lambda payload, td: pd.DataFrame({"x": [1]}),
        success_event="fetched_market_day",
        error_label="daily prices",
    )
    assert calls["n"] == 3
    assert len(frame) == 1


def test_fetch_csv_with_retry_raises_after_exhaustion(monkeypatch) -> None:
    """所有嘗試皆失敗時應拋出 RuntimeError 並重試 max_retries 次。"""
    import requests as _requests

    from sentinel.config import Settings
    from sentinel.datasources import providers as providers_module

    calls = {"n": 0}

    def fake_fetch_text(url, *, params=None, headers=None, timeout_seconds=0):
        calls["n"] += 1
        raise _requests.RequestException("boom")

    monkeypatch.setattr(providers_module, "fetch_text", fake_fetch_text)
    monkeypatch.setattr(providers_module.time, "sleep", lambda _s: None)

    settings = Settings(
        _env_file=None,
        max_retries=3,
        retry_backoff_seconds=0,
        retry_jitter_seconds=0,
        min_delay_seconds=0,
        max_delay_seconds=0,
    )
    with pytest.raises(RuntimeError) as exc_info:
        providers_module.fetch_csv_with_retry(
            endpoint="https://example.test/csv",
            params={},
            headers={},
            settings=settings,
            market="TWSE",
            trading_date=date(2025, 3, 5),
            parse_fn=lambda payload, td: pd.DataFrame({"x": [1]}),
            success_event="fetched_market_day",
            error_label="daily prices",
        )
    assert calls["n"] == 3
    assert "Failed to fetch TWSE daily prices for 2025-03-05" in str(exc_info.value)
