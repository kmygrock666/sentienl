from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy.orm import Session

from sentinel.db import create_db_engine, create_schema
from sentinel.intraday.trades import compute_open_trades_pnl
from sentinel.models import IntradayTrade


@pytest.fixture()
def session():
    engine = create_db_engine("sqlite://")
    create_schema(engine)
    with Session(engine) as s:
        yield s


def _add_trade(
    session: Session,
    market: str,
    symbol: str,
    entry_price: float,
    shares: int = 1,
    status: str = "open",
) -> IntradayTrade:
    trade = IntradayTrade(
        market=market,
        symbol=symbol,
        entry_date=date(2026, 6, 9),
        entry_price=entry_price,
        shares=shares,
        status=status,
    )
    session.add(trade)
    session.commit()
    return trade


def test_compute_open_trades_pnl_returns_correct_pct_and_amount(session) -> None:
    _add_trade(session, "TWSE", "2330", entry_price=100.0, shares=2)
    _add_trade(session, "TPEX", "5483", entry_price=50.0, shares=3)

    def fake_fetcher(symbols: list[str], markets: list[str]) -> dict[tuple[str, str], float]:
        return {("TWSE", "2330"): 110.0, ("TPEX", "5483"): 45.0}

    results = compute_open_trades_pnl(session, quotes_fetcher=fake_fetcher)

    assert len(results) == 2
    by_symbol = {r["symbol"]: r for r in results}

    r1 = by_symbol["2330"]
    assert r1["market"] == "TWSE"
    assert r1["entry_price"] == pytest.approx(100.0)
    assert r1["shares"] == 2
    assert r1["current_price"] == pytest.approx(110.0)
    assert r1["unrealized_pct"] == pytest.approx(0.10)
    assert r1["unrealized_amount"] == pytest.approx(20.0)

    r2 = by_symbol["5483"]
    assert r2["current_price"] == pytest.approx(45.0)
    assert r2["unrealized_pct"] == pytest.approx(-0.10)
    assert r2["unrealized_amount"] == pytest.approx(-15.0)


def test_compute_open_trades_pnl_missing_quote_yields_none_fields(session) -> None:
    _add_trade(session, "TWSE", "2330", entry_price=100.0)
    _add_trade(session, "TWSE", "9999", entry_price=20.0)

    def fake_fetcher(symbols: list[str], markets: list[str]) -> dict[tuple[str, str], float]:
        return {("TWSE", "2330"): 105.0}

    results = compute_open_trades_pnl(session, quotes_fetcher=fake_fetcher)

    by_symbol = {r["symbol"]: r for r in results}
    missing = by_symbol["9999"]
    assert missing["current_price"] is None
    assert missing["unrealized_pct"] is None
    assert missing["unrealized_amount"] is None

    found = by_symbol["2330"]
    assert found["current_price"] == pytest.approx(105.0)


def test_compute_open_trades_pnl_closed_only_returns_empty(session) -> None:
    _add_trade(session, "TWSE", "2330", entry_price=100.0, status="closed")

    def fake_fetcher(symbols: list[str], markets: list[str]) -> dict[tuple[str, str], float]:
        raise AssertionError("fetcher should not be called when no open trades")

    assert compute_open_trades_pnl(session, quotes_fetcher=fake_fetcher) == []


def test_compute_open_trades_pnl_passes_symbols_and_markets_to_fetcher(session) -> None:
    _add_trade(session, "TWSE", "2330", entry_price=100.0)
    _add_trade(session, "TPEX", "5483", entry_price=50.0)
    _add_trade(session, "TWSE", "0050", entry_price=180.0, status="closed")

    seen: dict[str, list[str]] = {}

    def fake_fetcher(symbols: list[str], markets: list[str]) -> dict[tuple[str, str], float]:
        seen["symbols"] = list(symbols)
        seen["markets"] = list(markets)
        return {}

    compute_open_trades_pnl(session, quotes_fetcher=fake_fetcher)

    assert sorted(zip(seen["markets"], seen["symbols"])) == [
        ("TPEX", "5483"),
        ("TWSE", "2330"),
    ]
