from __future__ import annotations

from datetime import date

import pandas as pd
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from sentinel.datasources.institutional import (
    INSTITUTIONAL_ENRICH_COLUMNS,
    TpexInstitutionalProvider,
    TwseT86Provider,
    build_institutional_provider,
    enrich_with_institutional,
    load_institutional_frame,
)
from sentinel.domain.models import InstitutionalFlow
from sentinel.storage.engine import create_db_engine, create_schema
from sentinel.storage.persistence import upsert_institutional_flows

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


_FLOW_COLUMNS = [
    "market",
    "symbol",
    "trading_date",
    "foreign_net",
    "investment_trust_net",
    "dealer_net",
    "total_net",
]


def _flow_row(
    symbol: str,
    trading_date: date,
    foreign_net: int | None,
    market: str = "TWSE",
) -> dict:
    return {
        "market": market,
        "symbol": symbol,
        "trading_date": trading_date,
        "foreign_net": foreign_net,
        "investment_trust_net": 1_000,
        "dealer_net": -500,
        # total = foreign + trust(1000) + dealer(-500)
        "total_net": (foreign_net or 0) + 1_000 - 500,
    }


def _price_frame(rows: list[tuple[str, date]], market: str = "TWSE") -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "market": market,
                "symbol": symbol,
                "trading_date": trading_date,
                "close": 100.0,
            }
            for symbol, trading_date in rows
        ]
    )


def test_load_institutional_frame_filters_date_range(tmp_path) -> None:
    database_path = tmp_path / "institutional_load.db"
    engine = create_db_engine(f"sqlite:///{database_path}")
    create_schema(engine)

    flows = pd.DataFrame(
        [
            _flow_row("2330", date(2025, 3, 3), 100),
            _flow_row("2330", date(2025, 3, 4), 200),
            _flow_row("2330", date(2025, 3, 5), 300),
            _flow_row("2330", date(2025, 3, 6), 400),
            _flow_row("2330", date(2025, 3, 7), 500),
        ]
    )
    with Session(engine) as session:
        upsert_institutional_flows(session, flows)
        session.commit()

    with Session(engine) as session:
        loaded = load_institutional_frame(
            session, start_date=date(2025, 3, 4), end_date=date(2025, 3, 6)
        )

    assert list(loaded.columns) == _FLOW_COLUMNS
    assert sorted(loaded["trading_date"]) == [
        date(2025, 3, 4),
        date(2025, 3, 5),
        date(2025, 3, 6),
    ]
    assert sorted(loaded["foreign_net"]) == [200, 300, 400]


def test_load_institutional_frame_empty_range_returns_empty_frame(tmp_path) -> None:
    database_path = tmp_path / "institutional_load_empty.db"
    engine = create_db_engine(f"sqlite:///{database_path}")
    create_schema(engine)

    with Session(engine) as session:
        loaded = load_institutional_frame(
            session, start_date=date(2025, 3, 4), end_date=date(2025, 3, 6)
        )

    assert loaded.empty
    assert list(loaded.columns) == _FLOW_COLUMNS


def test_enrich_with_institutional_rolling_and_streak() -> None:
    # 2330: 3/3=+100, 3/4=+200, 3/5=資料缺漏(gap), 3/6=-50, 3/7=+300
    frame = _price_frame(
        [
            ("2330", date(2025, 3, 3)),
            ("2330", date(2025, 3, 4)),
            ("2330", date(2025, 3, 5)),
            ("2330", date(2025, 3, 6)),
            ("2330", date(2025, 3, 7)),
        ]
    )
    flows = pd.DataFrame(
        [
            _flow_row("2330", date(2025, 3, 3), 100),
            _flow_row("2330", date(2025, 3, 4), 200),
            _flow_row("2330", date(2025, 3, 6), -50),
            _flow_row("2330", date(2025, 3, 7), 300),
        ]
    )

    enriched = enrich_with_institutional(frame, flows)

    for column in INSTITUTIONAL_ENRICH_COLUMNS:
        assert column in enriched.columns

    foreign_net = enriched["foreign_net"].tolist()
    assert foreign_net[0] == 100
    assert foreign_net[1] == 200
    assert pd.isna(foreign_net[2])  # gap day
    assert foreign_net[3] == -50
    assert foreign_net[4] == 300

    # rolling(5, min_periods=1) sum skips the NaN gap day:
    # [100, 100+200, 100+200, 100+200-50, 100+200-50+300]
    assert enriched["foreign_net_5d"].tolist() == [100, 300, 300, 250, 550]

    # streak: +100→1, +200→2, gap(NaN)→0, -50→0, +300→1
    assert enriched["foreign_buy_streak"].tolist() == [1, 2, 0, 0, 1]


def test_enrich_with_institutional_does_not_leak_across_symbols() -> None:
    # Interleaved input order on purpose: grouping must isolate each symbol.
    frame = _price_frame(
        [
            ("2330", date(2025, 3, 3)),
            ("2317", date(2025, 3, 3)),
            ("2330", date(2025, 3, 4)),
            ("2317", date(2025, 3, 4)),
        ]
    )
    flows = pd.DataFrame(
        [
            _flow_row("2330", date(2025, 3, 3), 10),
            _flow_row("2330", date(2025, 3, 4), 20),
            _flow_row("2317", date(2025, 3, 3), 1_000),
            _flow_row("2317", date(2025, 3, 4), -2_000),
        ]
    )

    enriched = enrich_with_institutional(frame, flows)

    # Original row order is preserved.
    assert enriched["symbol"].tolist() == ["2330", "2317", "2330", "2317"]

    tsmc = enriched[enriched["symbol"] == "2330"].sort_values("trading_date")
    hon_hai = enriched[enriched["symbol"] == "2317"].sort_values("trading_date")
    assert tsmc["foreign_net_5d"].tolist() == [10, 30]
    assert tsmc["foreign_buy_streak"].tolist() == [1, 2]
    assert hon_hai["foreign_net_5d"].tolist() == [1_000, -1_000]
    assert hon_hai["foreign_buy_streak"].tolist() == [1, 0]


def test_enrich_with_institutional_empty_flows_adds_nan_columns() -> None:
    frame = _price_frame([("2330", date(2025, 3, 3)), ("2330", date(2025, 3, 4))])
    original = frame.copy(deep=True)

    enriched = enrich_with_institutional(frame, pd.DataFrame(columns=_FLOW_COLUMNS))

    for column in INSTITUTIONAL_ENRICH_COLUMNS:
        assert column in enriched.columns
        assert enriched[column].isna().all()
    # 輸入 frame 不可被變異
    pd.testing.assert_frame_equal(frame, original)


def test_enrich_with_institutional_handles_datetime64_trading_date() -> None:
    frame = _price_frame([("2330", date(2025, 3, 3)), ("2330", date(2025, 3, 4))])
    frame["trading_date"] = pd.to_datetime(frame["trading_date"])
    flows = pd.DataFrame(
        [
            _flow_row("2330", date(2025, 3, 3), 100),
            _flow_row("2330", date(2025, 3, 4), 200),
        ]
    )

    enriched = enrich_with_institutional(frame, flows)

    assert enriched["foreign_net"].tolist() == [100, 200]
    assert enriched["foreign_net_5d"].tolist() == [100, 300]
    assert enriched["foreign_buy_streak"].tolist() == [1, 2]
    # 原本的 trading_date dtype / 值必須保留
    assert pd.api.types.is_datetime64_any_dtype(enriched["trading_date"])
    assert enriched["trading_date"].tolist() == [
        pd.Timestamp(2025, 3, 3),
        pd.Timestamp(2025, 3, 4),
    ]
