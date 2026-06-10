from __future__ import annotations

from datetime import date

import pandas as pd
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from sentinel.db import create_db_engine, create_schema
from sentinel.institutional import (
    TpexInstitutionalProvider,
    TwseT86Provider,
    build_institutional_provider,
)
from sentinel.models import InstitutionalFlow
from sentinel.persistence import upsert_institutional_flows

_TWSE_PAYLOAD = """
"114年03月05日 三大法人買賣超日報"
"證券代號","證券名稱","外陸資買進股數(不含外資自營商)","外陸資賣出股數(不含外資自營商)","外陸資買賣超股數(不含外資自營商)","外資自營商買進股數","外資自營商賣出股數","外資自營商買賣超股數","投信買進股數","投信賣出股數","投信買賣超股數","自營商買賣超股數","自營商買進股數(自行買賣)","自營商賣出股數(自行買賣)","自營商買賣超股數(自行買賣)","自營商買進股數(避險)","自營商賣出股數(避險)","自營商買賣超股數(避險)","三大法人買賣超股數"
"2330","台積電","30,000,000","10,000,000","20,000,000","0","0","0","3,000,000","1,000,000","2,000,000","500,000","400,000","200,000","200,000","600,000","300,000","300,000","22,500,000"
"2317","鴻海","5,000,000","6,234,567","-1,234,567","0","0","0","100,000","300,000","-200,000","-50,000","10,000","30,000","-20,000","20,000","50,000","-30,000","-1,484,567"
"""

_TPEX_PAYLOAD = """
"資料日期:114/03/05"
"代號","名稱","外資及陸資(不含外資自營商)-買進股數","外資及陸資(不含外資自營商)-賣出股數","外資及陸資(不含外資自營商)-買賣超股數","外資自營商-買賣超股數","投信-買進股數","投信-賣出股數","投信-買賣超股數","自營商-買賣超股數","自營商(自行買賣)-買賣超股數","自營商(避險)-買賣超股數","三大法人買賣超股數合計"
"5483","中美晶","1,000,000","2,500,000","-1,500,000","0","800,000","200,000","600,000","100,000","60,000","40,000","-800,000"
"8069","元太","4,000,000","1,000,000","3,000,000","0","500,000","100,000","400,000","-200,000","-150,000","-50,000","3,200,000"
"""


def test_twse_t86_parser_extracts_flow_rows() -> None:
    provider = TwseT86Provider()

    frame = provider._parse_csv(_TWSE_PAYLOAD, trading_date=date(2025, 3, 5))

    assert list(frame["symbol"]) == ["2330", "2317"]
    assert frame.iloc[0]["market"] == "TWSE"
    assert frame.iloc[0]["trading_date"] == date(2025, 3, 5)
    assert frame.iloc[0]["foreign_net"] == 20_000_000
    assert frame.iloc[0]["investment_trust_net"] == 2_000_000
    assert frame.iloc[0]["dealer_net"] == 500_000
    assert frame.iloc[0]["total_net"] == 22_500_000
    assert frame.iloc[1]["foreign_net"] == -1_234_567
    assert frame.iloc[1]["investment_trust_net"] == -200_000
    assert frame.iloc[1]["dealer_net"] == -50_000
    assert frame.iloc[1]["total_net"] == -1_484_567
    assert list(frame.columns) == [
        "market",
        "symbol",
        "trading_date",
        "foreign_net",
        "investment_trust_net",
        "dealer_net",
        "total_net",
    ]


def test_twse_t86_parser_rejects_mismatched_date() -> None:
    provider = TwseT86Provider()

    frame = provider._parse_csv(_TWSE_PAYLOAD, trading_date=date(2026, 3, 5))

    assert frame.empty


def test_tpex_parser_extracts_flow_rows() -> None:
    provider = TpexInstitutionalProvider()

    frame = provider._parse_csv(_TPEX_PAYLOAD, trading_date=date(2025, 3, 5))

    assert list(frame["symbol"]) == ["5483", "8069"]
    assert frame.iloc[0]["market"] == "TPEX"
    assert frame.iloc[0]["trading_date"] == date(2025, 3, 5)
    assert frame.iloc[0]["foreign_net"] == -1_500_000
    assert frame.iloc[0]["investment_trust_net"] == 600_000
    assert frame.iloc[0]["dealer_net"] == 100_000
    assert frame.iloc[0]["total_net"] == -800_000
    assert frame.iloc[1]["foreign_net"] == 3_000_000
    assert frame.iloc[1]["total_net"] == 3_200_000


def test_tpex_parser_rejects_mismatched_date() -> None:
    provider = TpexInstitutionalProvider()

    frame = provider._parse_csv(_TPEX_PAYLOAD, trading_date=date(2026, 3, 5))

    assert frame.empty


def test_build_institutional_provider_factory() -> None:
    assert isinstance(build_institutional_provider("TWSE"), TwseT86Provider)
    assert isinstance(build_institutional_provider("tpex"), TpexInstitutionalProvider)
    with pytest.raises(ValueError):
        build_institutional_provider("NYSE")


def test_upsert_institutional_flows_round_trip(tmp_path) -> None:
    database_path = tmp_path / "institutional.db"
    engine = create_db_engine(f"sqlite:///{database_path}")
    create_schema(engine)

    flows = pd.DataFrame(
        [
            {
                "market": "TWSE",
                "symbol": "2330",
                "trading_date": date(2025, 3, 5),
                "foreign_net": 20_000_000,
                "investment_trust_net": 2_000_000,
                "dealer_net": 500_000,
                "total_net": 22_500_000,
            },
            {
                "market": "TPEX",
                "symbol": "8069",
                "trading_date": date(2025, 3, 5),
                "foreign_net": 3_000_000,
                "investment_trust_net": None,
                "dealer_net": -200_000,
                "total_net": 3_200_000,
            },
        ]
    )

    with Session(engine) as session:
        count = upsert_institutional_flows(session, flows)
        session.commit()
    assert count == 2

    # Re-upsert with changed values: conflict update must overwrite, not duplicate
    updated_flows = flows.copy()
    updated_flows.loc[0, "foreign_net"] = -7_777_777
    updated_flows.loc[0, "total_net"] = -5_277_777
    with Session(engine) as session:
        count = upsert_institutional_flows(session, updated_flows)
        session.commit()
    assert count == 2

    with Session(engine) as session:
        rows = session.execute(
            select(InstitutionalFlow).order_by(InstitutionalFlow.symbol)
        ).scalars()
        by_symbol = {row.symbol: row for row in rows}

    assert len(by_symbol) == 2
    assert by_symbol["2330"].foreign_net == -7_777_777
    assert by_symbol["2330"].total_net == -5_277_777
    assert by_symbol["2330"].investment_trust_net == 2_000_000
    assert by_symbol["8069"].investment_trust_net is None
    assert by_symbol["8069"].dealer_net == -200_000
    assert by_symbol["8069"].trading_date == date(2025, 3, 5)


def test_upsert_institutional_flows_empty_frame_returns_zero(tmp_path) -> None:
    database_path = tmp_path / "institutional_empty.db"
    engine = create_db_engine(f"sqlite:///{database_path}")
    create_schema(engine)

    with Session(engine) as session:
        assert upsert_institutional_flows(session, pd.DataFrame()) == 0
