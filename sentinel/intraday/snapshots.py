from __future__ import annotations

import logging
from datetime import date, datetime

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from sentinel.domain.models import DailyPrice, IntradaySnapshot
from sentinel.intraday.fetcher import MISFetcher, parse_mis_data

logger = logging.getLogger(__name__)


def capture_intraday_snapshot(session: Session, snapshot_time: str, top_n: int = 400) -> int:
    """
    Capture a snapshot of the current price and volume for the top stocks.
    Usually run at 12:00.
    """
    # 1. Identify target stocks: yesterday's most active (volume)
    # Get the latest trading date in the DB (strictly before today)
    today = date.today()
    latest_date_stmt = (
        select(DailyPrice.trading_date)
        .where(DailyPrice.trading_date < today)
        .order_by(desc(DailyPrice.trading_date))
        .limit(1)
    )
    latest_date = session.execute(latest_date_stmt).scalar()

    if not latest_date:
        logger.error("No historical price data found to identify top stocks.")
        return 0

    logger.info(f"Identifying top {top_n} stocks by volume on {latest_date}...")

    target_stocks_stmt = (
        select(DailyPrice.market, DailyPrice.symbol)
        .where(DailyPrice.trading_date == latest_date)
        .order_by(desc(DailyPrice.volume))
        .limit(top_n)
    )
    targets = session.execute(target_stocks_stmt).all()

    if not targets:
        return 0

    symbols = [t.symbol for t in targets]
    markets = [t.market for t in targets]

    # 2. Fetch real-time data
    fetcher = MISFetcher()
    raw_msgs = fetcher.fetch_all(symbols, markets)

    # 3. Save snapshots
    today = date.today()
    count = 0
    for msg in raw_msgs:
        parsed = parse_mis_data(msg)
        if not parsed["symbol"]:
            continue

        # Upsert
        snapshot = session.get(
            IntradaySnapshot, (parsed["market"], parsed["symbol"], today, snapshot_time)
        )
        if not snapshot:
            snapshot = IntradaySnapshot(
                market=parsed["market"],
                symbol=parsed["symbol"],
                trading_date=today,
                snapshot_time=snapshot_time,
            )
            session.add(snapshot)

        snapshot.cumulative_volume = parsed["volume"]
        snapshot.last_price = parsed["close"]
        snapshot.updated_at = datetime.utcnow()
        count += 1

    session.commit()
    logger.info(f"Captured {count} intraday snapshots for {snapshot_time}.")
    return count
