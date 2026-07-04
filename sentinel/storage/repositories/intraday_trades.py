from __future__ import annotations

from typing import Optional

import pandas as pd
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from sentinel.models import IntradayTrade, Stock


def get_intraday_trades(engine: Engine, status: Optional[str] = None) -> pd.DataFrame:
    with Session(engine) as s:
        q = (
            s.query(IntradayTrade, Stock.name)
            .outerjoin(
                Stock,
                (Stock.market == IntradayTrade.market) & (Stock.symbol == IntradayTrade.symbol),
            )
            .order_by(IntradayTrade.entry_date.desc(), IntradayTrade.trade_id.desc())
        )
        if status:
            q = q.filter(IntradayTrade.status == status)
        rows = q.all()
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(
        [
            {
                "trade_id": r.IntradayTrade.trade_id,
                "市場": r.IntradayTrade.market,
                "代號": r.IntradayTrade.symbol,
                "名稱": r.name or "",
                "進場日": r.IntradayTrade.entry_date,
                "進場價": float(r.IntradayTrade.entry_price),
                "出場日": r.IntradayTrade.exit_date,
                "出場價": (
                    float(r.IntradayTrade.exit_price)
                    if r.IntradayTrade.exit_price is not None
                    else None
                ),
                "狀態": r.IntradayTrade.status,
                "損益": (
                    float(r.IntradayTrade.profit_loss)
                    if r.IntradayTrade.profit_loss is not None
                    else None
                ),
                "備註": r.IntradayTrade.notes or "",
            }
            for r in rows
        ]
    )
