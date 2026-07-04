from __future__ import annotations

from datetime import date
from typing import Optional

import pandas as pd
from sqlalchemy import func
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from sentinel.domain.models import MainForceDaily

_MAIN_FORCE_COLUMNS = ["日期", "主力買超", "主力賣超", "主力買賣超"]


def get_main_force_daily(engine: Engine, market: str, symbol: str, days: int = 240) -> pd.DataFrame:
    """近 N 個交易日的主力買賣超（券商分點 Top-N，張），依日期昇冪（供畫圖）。"""

    def _to_lots(value: int | None) -> int | None:
        return int(value / 1000) if value is not None else None

    with Session(engine) as s:
        rows = (
            s.query(MainForceDaily)
            .filter(MainForceDaily.market == market, MainForceDaily.symbol == symbol)
            .order_by(MainForceDaily.trading_date.desc())
            .limit(days)
            .all()
        )
    if not rows:
        return pd.DataFrame(columns=_MAIN_FORCE_COLUMNS)
    df = pd.DataFrame(
        [
            {
                "日期": r.trading_date,
                "主力買超": _to_lots(r.main_buy),
                "主力賣超": _to_lots(r.main_sell),
                "主力買賣超": _to_lots(r.main_net),
            }
            for r in rows
        ]
    )
    # 缺值保持為 NA（避免 None 混入時整欄被轉為 float）
    for col in _MAIN_FORCE_COLUMNS[1:]:
        df[col] = df[col].astype("Int64")
    return df.sort_values("日期").reset_index(drop=True)


def get_latest_main_force_dates(engine: Engine, symbols: list[str]) -> dict[str, Optional[date]]:
    """批次查詢各個股 MainForceDaily 最新 trading_date。

    回傳 {symbol: date | None}，清單中但 DB 無資料的個股映射到 None。
    """
    if not symbols:
        return {}
    with Session(engine) as s:
        rows = (
            s.query(MainForceDaily.symbol, func.max(MainForceDaily.trading_date))
            .filter(MainForceDaily.symbol.in_(symbols))
            .group_by(MainForceDaily.symbol)
            .all()
        )
    result: dict[str, Optional[date]] = {sym: None for sym in symbols}
    for sym, d in rows:
        result[sym] = d
    return result
