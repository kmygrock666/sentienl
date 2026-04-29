from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from typing import List, Optional

import pandas as pd
from sqlalchemy import select, func, and_
from sqlalchemy.orm import Session

from sentinel.models import DailyPrice, IntradayIndicator, Stock

logger = logging.getLogger(__name__)

def calculate_intraday_win_rates(
    session: Session,
    lookback_days: int = 180,
    gain_threshold: float = 0.05,
    min_samples: int = 5
) -> int:
    """
    Calculate historical win rate for stocks that showed strong momentum.
    Specifically: if today's gain >= gain_threshold, what is the probability
    that tomorrow's open is higher than today's close?
    
    Returns the number of indicators updated.
    """
    start_date = (date.today() - timedelta(days=lookback_days))
    
    # Get all active stocks
    stocks = session.execute(select(Stock).where(Stock.list_status == "active")).scalars().all()
    count = 0
    
    for stock in stocks:
        # Fetch price history
        stmt = (
            select(DailyPrice)
            .where(
                and_(
                    DailyPrice.market == stock.market,
                    DailyPrice.symbol == stock.symbol,
                    DailyPrice.trading_date >= start_date
                )
            )
            .order_by(DailyPrice.trading_date.asc())
        )
        prices_df = pd.read_sql(stmt, session.bind)
        
        if len(prices_df) < min_samples + 1:
            continue
            
        # Calculate daily returns
        prices_df["prev_close"] = prices_df["close"].shift(1)
        prices_df["daily_return"] = (prices_df["close"] - prices_df["prev_close"]) / prices_df["prev_close"]
        
        # Identify strong signal days (T)
        # We need a T+1 to check the open
        prices_df["next_open"] = prices_df["open"].shift(-1)
        
        # Signal condition: Gain >= 5%
        signals = prices_df[
            (prices_df["daily_return"] >= gain_threshold) & 
            (prices_df["next_open"].notnull())
        ]
        
        if len(signals) < min_samples:
            continue
            
        # Success condition: T+1 Open > T Close
        successes = signals[signals["next_open"] > signals["close"]]
        win_rate = len(successes) / len(signals)
        
        # Upsert into intraday_indicators
        indicator = session.get(IntradayIndicator, (stock.market, stock.symbol, "overnight_win_rate"))
        if not indicator:
            indicator = IntradayIndicator(
                market=stock.market,
                symbol=stock.symbol,
                indicator_name="overnight_win_rate"
            )
            session.add(indicator)
            
        indicator.value = win_rate
        indicator.sample_size = len(signals)
        indicator.last_updated_at = date.today()
        indicator.updated_at = datetime.utcnow()
        
        count += 1
        
    session.commit()
    logger.info(f"Updated intraday win rates for {count} stocks.")
    return count
