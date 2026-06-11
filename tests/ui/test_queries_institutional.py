"""測試 get_institutional_flow 查詢（法人籌碼）。"""

from __future__ import annotations

from datetime import date

import pandas as pd
import pytest
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from sentinel.db import create_db_engine, create_schema
from sentinel.models import InstitutionalFlow
from ui.services.queries import get_institutional_flow


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
