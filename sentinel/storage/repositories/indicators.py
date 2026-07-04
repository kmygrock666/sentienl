from __future__ import annotations

from datetime import date, timedelta
from typing import Optional

import pandas as pd
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from sentinel.domain.models import TechnicalIndicator


def get_indicators(
    engine: Engine,
    symbol: str,
    market: str,
    indicator_names: list[str],
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
) -> pd.DataFrame:
    if start_date is None:
        start_date = date.today() - timedelta(days=365)
    if end_date is None:
        end_date = date.today()
    with Session(engine) as s:
        rows = (
            s.query(
                TechnicalIndicator.trading_date,
                TechnicalIndicator.indicator_name,
                TechnicalIndicator.value,
            )
            .filter(
                TechnicalIndicator.market == market,
                TechnicalIndicator.symbol == symbol,
                TechnicalIndicator.indicator_name.in_(indicator_names),
                TechnicalIndicator.trading_date >= start_date,
                TechnicalIndicator.trading_date <= end_date,
            )
            .order_by(TechnicalIndicator.trading_date.asc())
            .all()
        )
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(
        [
            {
                "trading_date": r.trading_date,
                "indicator_name": r.indicator_name,
                "value": float(r.value),
            }
            for r in rows
        ]
    )
    return df.pivot(index="trading_date", columns="indicator_name", values="value").reset_index()
