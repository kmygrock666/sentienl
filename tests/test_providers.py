from __future__ import annotations

from datetime import date

from sentinel.providers import TpexDailyPriceProvider, TwseDailyPriceProvider


def test_twse_parser_extracts_price_rows() -> None:
    payload = """
    "114年03月05日 每日收盤行情(全部(不含權證、牛熊證))"
    "證券代號","證券名稱","成交股數","成交筆數","成交金額","開盤價","最高價","最低價","收盤價","漲跌(+/-)","漲跌價差","最後揭示買價","最後揭示買量","最後揭示賣價","最後揭示賣量","本益比"
    "1101","台泥","12,345,678","5,678","500,000,000","32.10","32.50","31.90","32.30","+","0.20","32.25","10","32.30","20","18.5"
    "1102","亞泥","7,654,321","4,321","300,000,000","41.00","41.30","40.50","41.20","+","0.10","41.15","5","41.20","8","15.2"
    """
    provider = TwseDailyPriceProvider()

    frame = provider._parse_csv(payload, trading_date=date(2026, 3, 5))

    assert list(frame["symbol"]) == ["1101", "1102"]
    assert frame.iloc[0]["close"] == 32.30
    assert frame.iloc[1]["volume"] == 7654321


def test_tpex_parser_extracts_price_rows() -> None:
    payload = """
    "櫃買中心上櫃股票每日收盤行情"
    "代號","名稱","收盤 ","漲跌","開盤 ","最高 ","最低","均價 ","成交股數","成交金額(元)","成交筆數"
    "8069","元太","250.50","+1.50","249.00","252.00","248.50","250.10","3,210,000","804,000,000","4,567"
    "5274","信驊","3,650.00","+20.00","3,620.00","3,680.00","3,610.00","3,645.00","120,000","438,000,000","980"
    """
    provider = TpexDailyPriceProvider()

    frame = provider._parse_csv(payload, trading_date=date(2026, 3, 5))

    assert list(frame["symbol"]) == ["8069", "5274"]
    assert frame.iloc[0]["close"] == 250.50
    assert frame.iloc[1]["turnover"] == 438000000
