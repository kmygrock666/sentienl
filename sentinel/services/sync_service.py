from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Dict, Optional

from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from sentinel.datasources.providers import normalize_market_name
from sentinel.storage.repositories.inspect_queries import get_latest_dates_by_market

DEFAULT_SYNC_START_DATE = date(2024, 1, 1)


@dataclass(frozen=True)
class SyncPlan:
    """每個市場各自的同步起點；互不影響。"""

    market_start_dates: Dict[str, date]
    end_date: date
    latest_dates: Dict[str, Optional[date]]

    @property
    def up_to_date(self) -> bool:
        return all(start > self.end_date for start in self.market_start_dates.values())

    @property
    def start_date(self) -> date:
        """全域起始日取最早市場起始點，供行事曆查詢使用。"""
        return min(self.market_start_dates.values())


def build_sync_plan(
    engine: Engine,
    markets: list,
    *,
    end_date: Optional[date] = None,
    default_start_date: date = DEFAULT_SYNC_START_DATE,
) -> SyncPlan:
    """依資料庫中各市場最新日期，計算增量同步的日期範圍。"""
    resolved_end = end_date or date.today()

    with Session(engine) as session:
        latest_dates = get_latest_dates_by_market(session)

    market_start_dates: Dict[str, date] = {}
    for market in markets:
        normalized = normalize_market_name(market)
        latest = latest_dates.get(normalized)
        if latest is None:
            market_start_dates[normalized] = default_start_date
        else:
            market_start_dates[normalized] = latest + timedelta(days=1)

    return SyncPlan(
        market_start_dates=market_start_dates,
        end_date=resolved_end,
        latest_dates=latest_dates,
    )
