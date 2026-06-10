from __future__ import annotations

from datetime import date

from sentinel.providers import TpexDailyPriceProvider, TwseDailyPriceProvider

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
    assert frame.iloc[0]["close"] == 32.30
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
