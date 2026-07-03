"""Tests for freshness queries used by the 每日盤後 page."""

from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from sentinel.db import create_db_engine, create_schema
from sentinel.models import InstitutionalFlow, MainForceDaily
from ui.services.queries import (
    get_latest_institutional_date,
    get_latest_main_force_dates,
)


@pytest.fixture()
def engine() -> Engine:
    eng = create_db_engine("sqlite://")
    create_schema(eng)
    return eng


# ── get_latest_institutional_date ─────────────────────────────────────────


def test_get_latest_institutional_date_returns_max(engine: Engine) -> None:
    """Returns the highest trading_date across all markets/symbols."""
    with Session(engine) as s:
        s.add(
            InstitutionalFlow(
                market="TWSE",
                symbol="2330",
                trading_date=date(2026, 6, 18),
                foreign_net=1000,
                investment_trust_net=0,
                dealer_net=0,
                total_net=1000,
            )
        )
        s.add(
            InstitutionalFlow(
                market="TPEX",
                symbol="5483",
                trading_date=date(2026, 6, 20),
                foreign_net=500,
                investment_trust_net=0,
                dealer_net=0,
                total_net=500,
            )
        )
        s.commit()

    result = get_latest_institutional_date(engine)

    assert result == date(2026, 6, 20)


def test_get_latest_institutional_date_empty_returns_none(engine: Engine) -> None:
    """Returns None when the table is empty."""
    assert get_latest_institutional_date(engine) is None


# ── get_latest_main_force_dates ───────────────────────────────────────────


def test_get_latest_main_force_dates_returns_per_symbol(engine: Engine) -> None:
    """Returns the max trading_date for each requested symbol."""
    with Session(engine) as s:
        for d in [date(2026, 6, 18), date(2026, 6, 20)]:
            s.add(
                MainForceDaily(
                    market="TWSE",
                    symbol="2330",
                    trading_date=d,
                    main_buy=10000,
                    main_sell=-5000,
                    main_net=5000,
                    top_n=15,
                )
            )
        s.add(
            MainForceDaily(
                market="TPEX",
                symbol="5347",
                trading_date=date(2026, 6, 19),
                main_buy=3000,
                main_sell=-1000,
                main_net=2000,
                top_n=15,
            )
        )
        s.commit()

    result = get_latest_main_force_dates(engine, ["2330", "5347"])

    assert result["2330"] == date(2026, 6, 20)
    assert result["5347"] == date(2026, 6, 19)


def test_get_latest_main_force_dates_missing_symbol_returns_none(engine: Engine) -> None:
    """Symbols with no data in the table map to None."""
    result = get_latest_main_force_dates(engine, ["9999", "1234"])

    assert result == {"9999": None, "1234": None}


def test_get_latest_main_force_dates_empty_symbols(engine: Engine) -> None:
    """Empty symbols list returns empty dict without querying."""
    assert get_latest_main_force_dates(engine, []) == {}
