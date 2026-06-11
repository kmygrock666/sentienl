"""測試法人籌碼查詢（單股明細、排行、連買榜）。"""

from __future__ import annotations

from datetime import date

import pandas as pd
import pytest
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from sentinel.db import create_db_engine, create_schema
from sentinel.models import InstitutionalFlow, MainForceDaily, Stock
from ui.services.queries import (
    get_foreign_streak_ranking,
    get_institutional_dates,
    get_institutional_flow,
    get_institutional_ranking,
    get_main_force_daily,
)


@pytest.fixture()
def engine() -> Engine:
    eng = create_db_engine("sqlite://")
    create_schema(eng)
    return eng


def _insert_flows(engine: Engine, rows: list[dict]) -> None:
    with Session(engine) as s:
        for row in rows:
            s.add(InstitutionalFlow(**row))
        s.commit()


def test_get_institutional_flow_ordering_and_conversion(engine: Engine) -> None:
    """應依日期由新到舊排序，且股數轉換為張數。"""
    _insert_flows(
        engine,
        [
            {
                "market": "TWSE",
                "symbol": "2330",
                "trading_date": date(2026, 6, 8),
                "foreign_net": 5000,
                "investment_trust_net": -2000,
                "dealer_net": 1000,
                "total_net": 4000,
            },
            {
                "market": "TWSE",
                "symbol": "2330",
                "trading_date": date(2026, 6, 10),
                "foreign_net": 12000,
                "investment_trust_net": 3000,
                "dealer_net": -1000,
                "total_net": 14000,
            },
            {
                "market": "TWSE",
                "symbol": "2330",
                "trading_date": date(2026, 6, 9),
                "foreign_net": -8000,
                "investment_trust_net": 0,
                "dealer_net": 2000,
                "total_net": -6000,
            },
        ],
    )

    df = get_institutional_flow(engine, "TWSE", "2330")

    assert list(df.columns) == ["日期", "外資", "投信", "自營商", "合計"]
    assert list(df["日期"]) == [date(2026, 6, 10), date(2026, 6, 9), date(2026, 6, 8)]
    # 股 → 張（除以 1000）
    assert list(df["外資"]) == [12, -8, 5]
    assert list(df["投信"]) == [3, 0, -2]
    assert list(df["自營商"]) == [-1, 2, 1]
    assert list(df["合計"]) == [14, -6, 4]


def test_get_institutional_flow_limit(engine: Engine) -> None:
    """days 參數應限制回傳筆數（取最近 N 日）。"""
    _insert_flows(
        engine,
        [
            {
                "market": "TWSE",
                "symbol": "2330",
                "trading_date": date(2026, 6, d),
                "foreign_net": d * 1000,
                "investment_trust_net": 0,
                "dealer_net": 0,
                "total_net": d * 1000,
            }
            for d in range(1, 6)
        ],
    )

    df = get_institutional_flow(engine, "TWSE", "2330", days=3)

    assert len(df) == 3
    assert list(df["日期"]) == [date(2026, 6, 5), date(2026, 6, 4), date(2026, 6, 3)]


def test_get_institutional_flow_none_passthrough(engine: Engine) -> None:
    """欄位為 None 時應保持缺值（NA），不可變成 0。"""
    _insert_flows(
        engine,
        [
            {
                "market": "TPEX",
                "symbol": "5483",
                "trading_date": date(2026, 6, 10),
                "foreign_net": 3000,
                "investment_trust_net": None,
                "dealer_net": None,
                "total_net": 3000,
            },
        ],
    )

    df = get_institutional_flow(engine, "TPEX", "5483")

    assert len(df) == 1
    assert df["外資"].iloc[0] == 3
    assert pd.isna(df["投信"].iloc[0])
    assert pd.isna(df["自營商"].iloc[0])
    assert df["合計"].iloc[0] == 3


def test_get_institutional_flow_filters_market_and_symbol(engine: Engine) -> None:
    """只回傳指定 market + symbol 的資料。"""
    _insert_flows(
        engine,
        [
            {
                "market": "TWSE",
                "symbol": "2330",
                "trading_date": date(2026, 6, 10),
                "foreign_net": 1000,
                "investment_trust_net": 0,
                "dealer_net": 0,
                "total_net": 1000,
            },
            {
                "market": "TPEX",
                "symbol": "2330",
                "trading_date": date(2026, 6, 10),
                "foreign_net": 2000,
                "investment_trust_net": 0,
                "dealer_net": 0,
                "total_net": 2000,
            },
        ],
    )

    df = get_institutional_flow(engine, "TWSE", "2330")

    assert len(df) == 1
    assert df["外資"].iloc[0] == 1


def test_get_institutional_flow_empty(engine: Engine) -> None:
    """無資料時應回傳含中文欄位的空 DataFrame。"""
    df = get_institutional_flow(engine, "TWSE", "9999")

    assert df.empty
    assert list(df.columns) == ["日期", "外資", "投信", "自營商", "合計"]


# ═══════════════════════════════════════════════════════════════════════════
# get_institutional_dates
# ═══════════════════════════════════════════════════════════════════════════


def test_get_institutional_dates_desc_and_limit(engine: Engine) -> None:
    """資料日應由新到舊排序、去重、並受 limit 限制。"""
    _insert_flows(
        engine,
        [
            {
                "market": m,
                "symbol": sym,
                "trading_date": date(2026, 6, d),
                "foreign_net": 1000,
                "investment_trust_net": 0,
                "dealer_net": 0,
                "total_net": 1000,
            }
            for d in range(1, 6)
            for m, sym in [("TWSE", "2330"), ("TPEX", "5483")]
        ],
    )

    dates = get_institutional_dates(engine)
    assert dates == [date(2026, 6, d) for d in range(5, 0, -1)]

    limited = get_institutional_dates(engine, limit=2)
    assert limited == [date(2026, 6, 5), date(2026, 6, 4)]


def test_get_institutional_dates_empty(engine: Engine) -> None:
    """無資料時回傳空 list。"""
    assert get_institutional_dates(engine) == []


# ═══════════════════════════════════════════════════════════════════════════
# get_institutional_ranking
# ═══════════════════════════════════════════════════════════════════════════

_D = date(2026, 6, 9)


def _insert_ranking_fixture(engine: Engine) -> None:
    with Session(engine) as s:
        s.add(Stock(market="TWSE", symbol="2330", name="台積電"))
        s.add(Stock(market="TPEX", symbol="5483", name="中美晶"))
        s.commit()
    _insert_flows(
        engine,
        [
            # 買超（正值）
            {
                "market": "TWSE",
                "symbol": "2330",
                "trading_date": _D,
                "foreign_net": 12000,
                "investment_trust_net": 3000,
                "dealer_net": 1000,
                "total_net": 16000,
            },
            {
                "market": "TPEX",
                "symbol": "5483",
                "trading_date": _D,
                "foreign_net": 5000,
                "investment_trust_net": 0,
                "dealer_net": 0,
                "total_net": 5000,
            },
            # 賣超（負值）
            {
                "market": "TWSE",
                "symbol": "2317",
                "trading_date": _D,
                "foreign_net": -8000,
                "investment_trust_net": -2000,
                "dealer_net": 0,
                "total_net": -10000,
            },
            {
                "market": "TWSE",
                "symbol": "2454",
                "trading_date": _D,
                "foreign_net": -3000,
                "investment_trust_net": 1000,
                "dealer_net": None,
                "total_net": -2000,
            },
            # 其他日期（不應入榜）
            {
                "market": "TWSE",
                "symbol": "9999",
                "trading_date": date(2026, 6, 8),
                "foreign_net": 99000,
                "investment_trust_net": 0,
                "dealer_net": 0,
                "total_net": 99000,
            },
        ],
    )


def test_get_institutional_ranking_buy_top(engine: Engine) -> None:
    """買超排行：只收正值、由大到小、股轉張、帶出名稱。"""
    _insert_ranking_fixture(engine)

    df = get_institutional_ranking(engine, _D, "foreign_net")

    assert list(df.columns) == ["市場", "代號", "名稱", "買賣超(張)"]
    assert list(df["代號"]) == ["2330", "5483"]
    assert list(df["名稱"]) == ["台積電", "中美晶"]
    assert list(df["買賣超(張)"]) == [12, 5]


def test_get_institutional_ranking_sell_ascending(engine: Engine) -> None:
    """賣超排行：只收負值、由小到大（賣最多在前）。"""
    _insert_ranking_fixture(engine)

    df = get_institutional_ranking(engine, _D, "foreign_net", ascending=True)

    assert list(df["代號"]) == ["2317", "2454"]
    assert list(df["買賣超(張)"]) == [-8, -3]


def test_get_institutional_ranking_market_filter(engine: Engine) -> None:
    """指定 market 時只回傳該市場。"""
    _insert_ranking_fixture(engine)

    df = get_institutional_ranking(engine, _D, "foreign_net", market="TPEX")

    assert list(df["代號"]) == ["5483"]
    assert list(df["市場"]) == ["TPEX"]


def test_get_institutional_ranking_limit(engine: Engine) -> None:
    """limit 應限制回傳筆數。"""
    _insert_ranking_fixture(engine)

    df = get_institutional_ranking(engine, _D, "foreign_net", limit=1)

    assert list(df["代號"]) == ["2330"]


def test_get_institutional_ranking_column_whitelist(engine: Engine) -> None:
    """net_column 不在白名單時應 raise ValueError（防注入）。"""
    with pytest.raises(ValueError):
        get_institutional_ranking(engine, _D, "foreign_net; DROP TABLE stocks")
    with pytest.raises(ValueError):
        get_institutional_ranking(engine, _D, "market")


def test_get_institutional_ranking_excludes_none_and_zero(engine: Engine) -> None:
    """None 與 0 不應出現在買超或賣超排行。"""
    _insert_ranking_fixture(engine)

    buy = get_institutional_ranking(engine, _D, "dealer_net")
    assert list(buy["代號"]) == ["2330"]  # 2454 為 None、2317/5483 為 0

    sell = get_institutional_ranking(engine, _D, "dealer_net", ascending=True)
    assert sell.empty
    assert list(sell.columns) == ["市場", "代號", "名稱", "買賣超(張)"]


# ═══════════════════════════════════════════════════════════════════════════
# get_foreign_streak_ranking
# ═══════════════════════════════════════════════════════════════════════════


def _insert_streak_fixture(engine: Engine) -> None:
    with Session(engine) as s:
        s.add(Stock(market="TWSE", symbol="2330", name="台積電"))
        s.commit()

    def _row(symbol: str, d: int, net: int | None) -> dict:
        return {
            "market": "TWSE",
            "symbol": symbol,
            "trading_date": date(2026, 6, d),
            "foreign_net": net,
            "investment_trust_net": 0,
            "dealer_net": 0,
            "total_net": net,
        }

    _insert_flows(
        engine,
        [
            # 2330：連 3 日買超（8, 9, 10），第 4 日（5）為賣超 → streak=3
            _row("2330", 5, -1000),
            _row("2330", 8, 3000),
            _row("2330", 9, 5500),
            _row("2330", 10, 12000),
            # 2317：中斷（9 賣超）→ streak=1 → 排除
            _row("2317", 8, 7000),
            _row("2317", 9, -2000),
            _row("2317", 10, 4000),
            # 2454：只有最後一日買超 → streak=1 → 排除
            _row("2454", 10, 9000),
            # 5483：缺 9 日資料 → 視為中斷 → streak=1 → 排除
            _row("5483", 8, 6000),
            _row("5483", 10, 3000),
            # 6510：最後一日賣超 → streak=0 → 排除
            _row("6510", 9, 8000),
            _row("6510", 10, -1000),
            # 3008：連 2 日買超 → streak=2
            _row("3008", 9, 2000),
            _row("3008", 10, 2000),
        ],
    )


def test_get_foreign_streak_ranking_hand_computed(engine: Engine) -> None:
    """連買天數與期間累計應與手算一致；streak<2 一律排除。"""
    _insert_streak_fixture(engine)

    df = get_foreign_streak_ranking(engine, end_date=date(2026, 6, 10))

    assert list(df.columns) == ["市場", "代號", "名稱", "連買天數", "期間累計(張)"]
    assert list(df["代號"]) == ["2330", "3008"]
    assert list(df["名稱"]) == ["台積電", ""]
    assert list(df["連買天數"]) == [3, 2]
    # 2330：(3000 + 5500 + 12000) / 1000 = 20（int 截斷）
    assert list(df["期間累計(張)"]) == [20, 4]


def test_get_foreign_streak_ranking_days_window(engine: Engine) -> None:
    """days 視窗應限制 streak 最大長度。"""
    _insert_streak_fixture(engine)

    df = get_foreign_streak_ranking(engine, end_date=date(2026, 6, 10), days=2)

    row = df[df["代號"] == "2330"].iloc[0]
    assert row["連買天數"] == 2
    assert row["期間累計(張)"] == 17  # (5500 + 12000) / 1000

    df_one = get_foreign_streak_ranking(engine, end_date=date(2026, 6, 10), days=1)
    assert df_one.empty  # 視窗內最多 streak=1，全部排除


# ═══════════════════════════════════════════════════════════════════════════
# get_main_force_daily
# ═══════════════════════════════════════════════════════════════════════════

_MF_COLUMNS = ["日期", "主力買超", "主力賣超", "主力買賣超"]


def _insert_main_force(engine: Engine, rows: list[dict]) -> None:
    with Session(engine) as s:
        for row in rows:
            s.add(MainForceDaily(**row))
        s.commit()


def test_get_main_force_daily_asc_order_and_lot_conversion(engine: Engine) -> None:
    """應依日期昇冪（供畫圖），且股數轉換為張數。"""
    _insert_main_force(
        engine,
        [
            {
                "market": "TPEX",
                "symbol": "5347",
                "trading_date": date(2026, 6, 10),
                "main_buy": 30000,
                "main_sell": -10000,
                "main_net": 20000,
                "top_n": 15,
            },
            {
                "market": "TPEX",
                "symbol": "5347",
                "trading_date": date(2026, 6, 9),
                "main_buy": 150000,
                "main_sell": -110000,
                "main_net": 40000,
                "top_n": 15,
            },
        ],
    )

    df = get_main_force_daily(engine, "TPEX", "5347")

    assert list(df.columns) == _MF_COLUMNS
    assert list(df["日期"]) == [date(2026, 6, 9), date(2026, 6, 10)]
    assert list(df["主力買超"]) == [150, 30]
    assert list(df["主力賣超"]) == [-110, -10]
    assert list(df["主力買賣超"]) == [40, 20]


def test_get_main_force_daily_none_passthrough_int64(engine: Engine) -> None:
    """None 欄位應保持缺值（Int64 NA），不可變成 0 或 float。"""
    _insert_main_force(
        engine,
        [
            {
                "market": "TWSE",
                "symbol": "2330",
                "trading_date": date(2026, 6, 10),
                "main_buy": 5000,
                "main_sell": None,
                "main_net": None,
                "top_n": 15,
            },
        ],
    )

    df = get_main_force_daily(engine, "TWSE", "2330")

    assert df["主力買超"].iloc[0] == 5
    assert pd.isna(df["主力賣超"].iloc[0])
    assert pd.isna(df["主力買賣超"].iloc[0])
    for col in _MF_COLUMNS[1:]:
        assert df[col].dtype == "Int64"


def test_get_main_force_daily_days_limit_keeps_latest(engine: Engine) -> None:
    """days 限制應保留最近 N 日，仍以昇冪輸出。"""
    _insert_main_force(
        engine,
        [
            {
                "market": "TPEX",
                "symbol": "5347",
                "trading_date": date(2026, 6, d),
                "main_buy": d * 1000,
                "main_sell": -1000,
                "main_net": d * 1000 - 1000,
                "top_n": 15,
            }
            for d in range(1, 6)
        ],
    )

    df = get_main_force_daily(engine, "TPEX", "5347", days=3)

    assert list(df["日期"]) == [date(2026, 6, 3), date(2026, 6, 4), date(2026, 6, 5)]


def test_get_main_force_daily_filters_market_and_empty(engine: Engine) -> None:
    """market/symbol 過濾生效；無資料時回傳含欄位的空 DataFrame。"""
    _insert_main_force(
        engine,
        [
            {
                "market": "TWSE",
                "symbol": "6201",
                "trading_date": date(2026, 6, 10),
                "main_buy": 1000,
                "main_sell": -2000,
                "main_net": -1000,
                "top_n": 15,
            },
        ],
    )

    assert get_main_force_daily(engine, "TPEX", "6201").empty
    empty = get_main_force_daily(engine, "TWSE", "9999")
    assert empty.empty
    assert list(empty.columns) == _MF_COLUMNS


def test_get_foreign_streak_ranking_market_filter_and_empty(engine: Engine) -> None:
    """market 篩選生效；無資料時回傳含欄位的空 DataFrame。"""
    _insert_streak_fixture(engine)

    df = get_foreign_streak_ranking(engine, end_date=date(2026, 6, 10), market="TPEX")
    assert df.empty
    assert list(df.columns) == ["市場", "代號", "名稱", "連買天數", "期間累計(張)"]

    empty_engine = create_db_engine("sqlite://")
    create_schema(empty_engine)
    df2 = get_foreign_streak_ranking(empty_engine, end_date=date(2026, 6, 10))
    assert df2.empty
    assert list(df2.columns) == ["市場", "代號", "名稱", "連買天數", "期間累計(張)"]
