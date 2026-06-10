from datetime import date
from typing import Dict, List, Optional

from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from sentinel.models import (
    DailyPrice,
    DataQuarantine,
    InstitutionalFlow,
    IntradaySnapshot,
    IntradayTrade,
    JobRun,
    MarginBalance,
    ScanResult,
    Stock,
    TechnicalIndicator,
    TradingCalendar,
)


def get_data_status(session: Session):
    tables = [
        ("daily_prices", DailyPrice.trading_date),
        ("technical_indicators", TechnicalIndicator.trading_date),
        ("scan_results", ScanResult.trading_date),
        ("trading_calendar", TradingCalendar.calendar_date),
        ("institutional_flows", InstitutionalFlow.trading_date),
        ("margin_balances", MarginBalance.trading_date),
        ("intraday_snapshots", IntradaySnapshot.trading_date),
        ("intraday_trades", IntradayTrade.entry_date),
    ]

    results = {}
    for name, col in tables:
        latest = session.scalar(select(func.max(col)))
        earliest = session.scalar(select(func.min(col)))
        count = session.scalar(select(func.count()).select_from(col.table))
        results[name] = {
            "latest": latest.isoformat() if latest else "N/A",
            "earliest": earliest.isoformat() if earliest else "N/A",
            "count": count or 0,
        }
    return results


def get_completeness(session: Session, target_date: date):
    # Expected: count of active stocks on a trading day
    expected_subq = (
        select(Stock.symbol, Stock.market)
        .join(TradingCalendar, (TradingCalendar.exchange == Stock.market))
        .where(TradingCalendar.calendar_date == target_date)
        .where(TradingCalendar.is_trading_day == True)
        .where(Stock.list_status == "active")
    ).subquery()

    expected_stocks = session.execute(select(expected_subq)).all()
    expected_count = len(expected_stocks)

    actual_count = (
        session.scalar(
            select(func.count())
            .select_from(DailyPrice)
            .where(DailyPrice.trading_date == target_date)
        )
        or 0
    )

    missing_query = (
        select(expected_subq.c.market, expected_subq.c.symbol)
        .outerjoin(
            DailyPrice,
            (DailyPrice.market == expected_subq.c.market)
            & (DailyPrice.symbol == expected_subq.c.symbol)
            & (DailyPrice.trading_date == target_date),
        )
        .where(DailyPrice.symbol == None)
    )
    missing_stocks = session.execute(missing_query).all()

    return {
        "date": target_date.isoformat(),
        "expected": expected_count,
        "actual": actual_count,
        "ratio": actual_count / expected_count if expected_count > 0 else 0,
        "missing": [{"market": m, "symbol": s} for m, s in missing_stocks],
    }


def get_scan_results(
    session: Session,
    strategy_id: Optional[str] = None,
    target_date: Optional[date] = None,
    min_volume: Optional[int] = None,
    limit: int = 50,
):
    stmt = (
        select(ScanResult, Stock.name, DailyPrice.close, DailyPrice.volume)
        .join(Stock, (Stock.market == ScanResult.market) & (Stock.symbol == ScanResult.symbol))
        .join(
            DailyPrice,
            (DailyPrice.market == ScanResult.market)
            & (DailyPrice.symbol == ScanResult.symbol)
            & (DailyPrice.trading_date == ScanResult.trading_date),
        )
    )

    if strategy_id:
        stmt = stmt.where(ScanResult.strategy_id == strategy_id)
    if target_date:
        stmt = stmt.where(ScanResult.trading_date == target_date)
    if min_volume:
        stmt = stmt.where(DailyPrice.volume >= min_volume)

    stmt = stmt.order_by(desc(ScanResult.score)).limit(limit)

    results = session.execute(stmt).all()
    return [
        {
            "market": r.ScanResult.market,
            "symbol": r.ScanResult.symbol,
            "name": r.name,
            "strategy": r.ScanResult.strategy_id,
            "date": r.ScanResult.trading_date.isoformat(),
            "score": float(r.ScanResult.score) if r.ScanResult.score else 0,
            "close": float(r.close),
            "volume": int(r.volume),
            "signals": r.ScanResult.signals_json,
        }
        for r in results
    ]


def get_job_logs(session: Session, limit: int = 20):
    stmt = select(JobRun).order_by(desc(JobRun.start_time)).limit(limit)
    jobs = session.scalars(stmt).all()
    return [
        {
            "run_id": j.run_id,
            "job": j.job_name,
            "status": j.status,
            "start": j.start_time.isoformat(),
            "end": j.end_time.isoformat() if j.end_time else "N/A",
            "in": j.rows_in,
            "out": j.rows_out,
            "error": j.error_summary,
        }
        for j in jobs
    ]


def get_quarantine_logs(session: Session, limit: int = 20):
    stmt = select(DataQuarantine).order_by(desc(DataQuarantine.detected_at)).limit(limit)
    entries = session.scalars(stmt).all()
    return [
        {
            "id": e.quarantine_id,
            "table": e.source_table,
            "pk": e.source_pk_or_batch,
            "rule": e.violated_rule,
            "detected_at": e.detected_at.isoformat(),
            "resolution": e.resolution,
        }
        for e in entries
    ]


def get_latest_dates_by_market(session: Session) -> Dict[str, date]:
    """
    獲取資料庫內各個市場 (market) 最後一筆成交價的日期。
    """
    stmt = select(DailyPrice.market, func.max(DailyPrice.trading_date)).group_by(DailyPrice.market)
    results = session.execute(stmt).all()
    return {market: latest_date for market, latest_date in results}
