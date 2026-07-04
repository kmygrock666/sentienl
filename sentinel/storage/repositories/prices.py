from __future__ import annotations

from datetime import date, timedelta
from typing import Optional

import pandas as pd
from sqlalchemy import func
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from sentinel.models import DailyPrice


def get_data_freshness(engine: Engine) -> pd.DataFrame:
    with Session(engine) as s:
        rows = (
            s.query(
                DailyPrice.market,
                func.max(DailyPrice.trading_date).label("latest_date"),
                func.count(DailyPrice.symbol.distinct()).label("symbol_count"),
            )
            .group_by(DailyPrice.market)
            .all()
        )
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(
        [
            {"market": r.market, "latest_date": r.latest_date, "symbol_count": r.symbol_count}
            for r in rows
        ]
    )


def get_daily_prices(
    engine: Engine,
    symbol: str,
    market: str,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
) -> pd.DataFrame:
    if start_date is None:
        start_date = date.today() - timedelta(days=365)
    if end_date is None:
        end_date = date.today()
    with Session(engine) as s:
        rows = (
            s.query(DailyPrice)
            .filter(
                DailyPrice.market == market,
                DailyPrice.symbol == symbol,
                DailyPrice.trading_date >= start_date,
                DailyPrice.trading_date <= end_date,
            )
            .order_by(DailyPrice.trading_date.asc())
            .all()
        )
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(
        [
            {
                "trading_date": r.trading_date,
                "open": float(r.open),
                "high": float(r.high),
                "low": float(r.low),
                "close": float(r.close),
                "volume": r.volume,
            }
            for r in rows
        ]
    )


def get_latest_price_date(engine: Engine) -> Optional[date]:
    with Session(engine) as s:
        return s.query(func.max(DailyPrice.trading_date)).scalar()
