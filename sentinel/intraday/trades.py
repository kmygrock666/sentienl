from __future__ import annotations

import logging
from datetime import date
from typing import Any, Dict, List

from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from sentinel.models import DailyPrice, IntradayTrade

logger = logging.getLogger(__name__)

def record_intraday_trades(session: Session, results: List[Dict[str, Any]]):
    """
    Record the top results as simulated entry trades.
    Only records the top 5 to avoid noise.
    """
    today = date.today()
    # Limit to top 5
    top_picks = results[:5]
    
    for r in top_picks:
        # Check if already recorded today
        stmt = select(IntradayTrade).where(
            and_(
                IntradayTrade.market == r["market"],
                IntradayTrade.symbol == r["symbol"],
                IntradayTrade.entry_date == today
            )
        )
        existing = session.execute(stmt).scalar()
        
        if existing:
            continue
            
        trade = IntradayTrade(
            market=r["market"],
            symbol=r["symbol"],
            entry_date=today,
            entry_price=r["close"],
            shares=1,  # Default 1 share for profit calculation
            status="open",
            notes=f"Tomorrow's Star 13:00 scan (Score: {r['score']:.2f}, WinRate: {r['win_rate']:.0%})"
        )
        session.add(trade)
        
    session.commit()
    if top_picks:
        logger.info(f"Recorded {len(top_picks)} simulated trades for {today}.")

def update_intraday_trades(session: Session, real_time: bool = False, price_type: str = "open", allow_today: bool = False) -> int:
    """
    Find open trades and close them.
    By default, it simulates "sell at next open" logic and skips trades opened today.
    If real_time is True, use MISFetcher to get the current day's prices.
    If allow_today is True, it allows closing trades that were opened today (useful for testing).
    """
    today = date.today()
    
    # Find all open trades
    stmt = select(IntradayTrade).where(IntradayTrade.status == "open")
    open_trades = session.execute(stmt).scalars().all()
    
    if not open_trades:
        return 0
        
    # Pre-fetch real-time data if requested
    real_time_prices = {}
    if real_time:
        from sentinel.intraday.fetcher import MISFetcher, parse_mis_data
        symbols = [t.symbol for t in open_trades if (allow_today or t.entry_date < today)]
        markets = [t.market for t in open_trades if (allow_today or t.entry_date < today)]
        if symbols:
            fetcher = MISFetcher()
            raw_msgs = fetcher.fetch_all(symbols, markets)
            for msg in raw_msgs:
                p = parse_mis_data(msg)
                if p["symbol"]:
                    # Respect requested price_type (open or last) -> map 'last' to 'close' from MIS parsed data
                    price_key = "close" if price_type == "last" else price_type
                    selected_price = p.get(price_key)
                    if selected_price:
                        real_time_prices[(p["market"], p["symbol"])] = selected_price

    count = 0
    for trade in open_trades:
        # Don't close trades opened TODAY (must wait until next day), unless allow_today is True
        if not allow_today and trade.entry_date >= today:
            continue
            
        exit_price = None
        
        if real_time:
            exit_price = real_time_prices.get((trade.market, trade.symbol))
        else:
            # Try to find today's price in DB (DailyPrice table)
            price_stmt = select(DailyPrice).where(
                and_(
                    DailyPrice.market == trade.market,
                    DailyPrice.symbol == trade.symbol,
                    DailyPrice.trading_date == today
                )
            )
            price = session.execute(price_stmt).scalar()
            if price:
                exit_price = float(price.open)
        
        if exit_price and exit_price > 0:
            trade.exit_date = today
            trade.exit_price = float(exit_price)
            # Simple profit/loss ratio
            trade.profit_loss = (trade.exit_price - float(trade.entry_price)) / float(trade.entry_price)
            trade.status = "closed"
            count += 1
            
    session.commit()
    if count > 0:
        logger.info(f"Closed {count} intraday trades using today's {price_type} prices.")
        
    return count
        
def monitor_and_close_intraday_trades(session: Session, threshold: float = 0.02, force_close: bool = False, allow_today: bool = False) -> int:
    """
    Monitor open trades and close them if they hit SL/TP threshold (2%)
    or if force_close is True (at 09:30).
    """
    today = date.today()
    stmt = select(IntradayTrade).where(IntradayTrade.status == "open")
    open_trades = session.execute(stmt).scalars().all()
    
    if not open_trades:
        return 0

    # Filter trades opened before today
    trades_to_check = open_trades if allow_today else [t for t in open_trades if t.entry_date < today]
    if not trades_to_check:
        return 0

    from sentinel.intraday.fetcher import MISFetcher, parse_mis_data
    symbols = [t.symbol for t in trades_to_check]
    markets = [t.market for t in trades_to_check]
    
    fetcher = MISFetcher()
    raw_msgs = fetcher.fetch_all(symbols, markets)
    real_time_prices = {}
    for msg in raw_msgs:
        p = parse_mis_data(msg)
        if p["symbol"] and p.get("close") is not None:
            real_time_prices[(p["market"], p["symbol"])] = p["close"]

    count = 0
    for trade in trades_to_check:
        current_price = real_time_prices.get((trade.market, trade.symbol))
        if not current_price:
            continue
            
        pl_ratio = (float(current_price) - float(trade.entry_price)) / float(trade.entry_price)
        
        should_close = False
        reason = ""
        
        if force_close:
            should_close = True
            reason = "Time Cutoff (09:30)"
        elif pl_ratio >= threshold:
            should_close = True
            reason = f"Take Profit (+{pl_ratio:.2%})"
        elif pl_ratio <= -threshold:
            should_close = True
            reason = f"Stop Loss ({pl_ratio:.2%})"
            
        if should_close:
            trade.exit_date = today
            trade.exit_price = float(current_price)
            trade.profit_loss = pl_ratio
            trade.status = "closed"
            trade.notes = f"{trade.notes or ''} | Closed via: {reason}"
            count += 1
            logger.info(f"Closing {trade.symbol} at {current_price} (P/L: {pl_ratio:.2%}) - Reason: {reason}")
            
    if count > 0:
        session.commit()
        
    return count
def add_manual_intraday_trade(session: Session, market: str, symbol: str, entry_price: float, notes: str = None) -> bool:
    """
    Manually add a simulated intraday trade to the database.
    If market is None, auto-detect from the Stock table.
    """
    from sentinel.models import Stock
    
    if market is None:
        # Auto-detect market from Stock table
        stock_stmt = select(Stock).where(Stock.symbol == symbol)
        stocks = session.execute(stock_stmt).scalars().all()
        if len(stocks) == 0:
            logger.error(f"Cannot add trade: Stock {symbol} not found in any market.")
            return False
        elif len(stocks) > 1:
            markets_found = [s.market for s in stocks]
            logger.error(f"Cannot add trade: Stock {symbol} found in multiple markets ({markets_found}). Please specify --market.")
            return False
        market = stocks[0].market
        logger.info(f"Auto-detected market for {symbol}: {market}")
    
    # Check if stock exists
    stock_stmt = select(Stock).where(and_(Stock.market == market, Stock.symbol == symbol))
    stock = session.execute(stock_stmt).scalar()
    if not stock:
        logger.error(f"Cannot add trade: Stock {market}:{symbol} not found in database.")
        return False
        
    today = date.today()
    trade = IntradayTrade(
        market=market,
        symbol=symbol,
        entry_date=today,
        entry_price=entry_price,
        shares=1,
        status="open",
        notes=notes or "Manually added trade"
    )
    session.add(trade)
    session.commit()
    logger.info(f"Manually recorded trade for {market}:{symbol} at {entry_price}.")
    return True

def clear_intraday_trades(session: Session) -> int:
    """
    Delete all simulated intraday trade records from the database.
    """
    from sqlalchemy import delete
    stmt = delete(IntradayTrade)
    res = session.execute(stmt)
    session.commit()
    count = res.rowcount
    logger.info(f"Cleared {count} intraday trade records.")
    return count
