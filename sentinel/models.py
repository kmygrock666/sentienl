from __future__ import annotations

from datetime import date, datetime
from typing import Any, Dict, Optional

from sqlalchemy import BigInteger, JSON, Boolean, Date, DateTime, Integer, Numeric, PrimaryKeyConstraint, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Stock(Base):
    __tablename__ = "stocks"
    __table_args__ = (PrimaryKeyConstraint("market", "symbol"),)

    market: Mapped[str] = mapped_column(String(16), nullable=False)
    symbol: Mapped[str] = mapped_column(String(16), nullable=False)
    name: Mapped[Optional[str]] = mapped_column(String(128))
    industry: Mapped[Optional[str]] = mapped_column(String(128))
    list_status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)


class DailyPrice(Base):
    __tablename__ = "daily_prices"
    __table_args__ = (PrimaryKeyConstraint("market", "symbol", "trading_date"),)

    market: Mapped[str] = mapped_column(String(16), nullable=False)
    symbol: Mapped[str] = mapped_column(String(16), nullable=False)
    trading_date: Mapped[date] = mapped_column(Date, nullable=False)
    open: Mapped[float] = mapped_column(Numeric(18, 4), nullable=False)
    high: Mapped[float] = mapped_column(Numeric(18, 4), nullable=False)
    low: Mapped[float] = mapped_column(Numeric(18, 4), nullable=False)
    close: Mapped[float] = mapped_column(Numeric(18, 4), nullable=False)
    volume: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    turnover: Mapped[Optional[int]] = mapped_column(Numeric(20, 0))
    adjusted_close: Mapped[Optional[float]] = mapped_column(Numeric(18, 4))
    data_version: Mapped[Optional[str]] = mapped_column(String(64))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)


class DailyPrice3D(Base):
    """3-day aggregated OHLCV bars. period_end_date is the last trading day in the 3-day block."""
    __tablename__ = "daily_prices_3d"
    __table_args__ = (PrimaryKeyConstraint("market", "symbol", "period_end_date"),)

    market: Mapped[str] = mapped_column(String(16), nullable=False)
    symbol: Mapped[str] = mapped_column(String(16), nullable=False)
    period_end_date: Mapped[date] = mapped_column(Date, nullable=False)
    open: Mapped[float] = mapped_column(Numeric(18, 4), nullable=False)
    high: Mapped[float] = mapped_column(Numeric(18, 4), nullable=False)
    low: Mapped[float] = mapped_column(Numeric(18, 4), nullable=False)
    close: Mapped[float] = mapped_column(Numeric(18, 4), nullable=False)
    volume: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    adjusted_close: Mapped[Optional[float]] = mapped_column(Numeric(18, 4))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)


class DailyPrice47D(Base):
    """47-day aggregated OHLCV bars. period_end_date is the last trading day in the 47-day block."""
    __tablename__ = "daily_prices_47d"
    __table_args__ = (PrimaryKeyConstraint("market", "symbol", "period_end_date"),)

    market: Mapped[str] = mapped_column(String(16), nullable=False)
    symbol: Mapped[str] = mapped_column(String(16), nullable=False)
    period_end_date: Mapped[date] = mapped_column(Date, nullable=False)
    open: Mapped[float] = mapped_column(Numeric(18, 4), nullable=False)
    high: Mapped[float] = mapped_column(Numeric(18, 4), nullable=False)
    low: Mapped[float] = mapped_column(Numeric(18, 4), nullable=False)
    close: Mapped[float] = mapped_column(Numeric(18, 4), nullable=False)
    volume: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    adjusted_close: Mapped[Optional[float]] = mapped_column(Numeric(18, 4))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)


class InstitutionalFlow(Base):
    __tablename__ = "institutional_flows"
    __table_args__ = (PrimaryKeyConstraint("market", "symbol", "trading_date"),)

    market: Mapped[str] = mapped_column(String(16), nullable=False)
    symbol: Mapped[str] = mapped_column(String(16), nullable=False)
    trading_date: Mapped[date] = mapped_column(Date, nullable=False)
    foreign_net: Mapped[Optional[int]] = mapped_column(Integer)
    investment_trust_net: Mapped[Optional[int]] = mapped_column(Integer)
    dealer_net: Mapped[Optional[int]] = mapped_column(Integer)
    total_net: Mapped[Optional[int]] = mapped_column(Integer)


class MarginBalance(Base):
    __tablename__ = "margin_balances"
    __table_args__ = (PrimaryKeyConstraint("market", "symbol", "trading_date"),)

    market: Mapped[str] = mapped_column(String(16), nullable=False)
    symbol: Mapped[str] = mapped_column(String(16), nullable=False)
    trading_date: Mapped[date] = mapped_column(Date, nullable=False)
    margin_balance: Mapped[Optional[int]] = mapped_column(Integer)
    short_balance: Mapped[Optional[int]] = mapped_column(Integer)
    margin_change: Mapped[Optional[int]] = mapped_column(Integer)
    short_change: Mapped[Optional[int]] = mapped_column(Integer)


class CorporateAction(Base):
    __tablename__ = "corporate_actions"

    action_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    market: Mapped[str] = mapped_column(String(16), nullable=False)
    symbol: Mapped[str] = mapped_column(String(16), nullable=False)
    ex_date: Mapped[date] = mapped_column(Date, nullable=False)
    action_type: Mapped[str] = mapped_column(String(32), nullable=False)
    cash_dividend: Mapped[Optional[float]] = mapped_column(Numeric(18, 4))
    stock_dividend_ratio: Mapped[Optional[float]] = mapped_column(Numeric(18, 8))
    adjustment_factor: Mapped[Optional[float]] = mapped_column(Numeric(18, 8))
    source: Mapped[Optional[str]] = mapped_column(String(256))


class TechnicalIndicator(Base):
    __tablename__ = "technical_indicators"
    __table_args__ = (
        PrimaryKeyConstraint("market", "symbol", "trading_date", "indicator_name", "params_hash", "calc_version"),
    )

    market: Mapped[str] = mapped_column(String(16), nullable=False)
    symbol: Mapped[str] = mapped_column(String(16), nullable=False)
    trading_date: Mapped[date] = mapped_column(Date, nullable=False)
    indicator_name: Mapped[str] = mapped_column(String(64), nullable=False)
    params_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    calc_version: Mapped[str] = mapped_column(String(64), nullable=False)
    value: Mapped[float] = mapped_column(Numeric(18, 8), nullable=False)
    source_field: Mapped[Optional[str]] = mapped_column(String(64))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)


class ScanResult(Base):
    __tablename__ = "scan_results"
    __table_args__ = (PrimaryKeyConstraint("run_id", "market", "symbol", "strategy_id"),)

    run_id: Mapped[str] = mapped_column(String(64), nullable=False)
    market: Mapped[str] = mapped_column(String(16), nullable=False)
    symbol: Mapped[str] = mapped_column(String(16), nullable=False)
    strategy_id: Mapped[str] = mapped_column(String(64), nullable=False)
    trading_date: Mapped[date] = mapped_column(Date, nullable=False)
    score: Mapped[Optional[float]] = mapped_column(Numeric(18, 8))
    signals_json: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON)
    data_version: Mapped[Optional[str]] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)


class JobRun(Base):
    __tablename__ = "job_runs"

    run_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    job_name: Mapped[str] = mapped_column(String(64), nullable=False)
    start_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_time: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    rows_in: Mapped[Optional[int]] = mapped_column(Integer)
    rows_out: Mapped[Optional[int]] = mapped_column(Integer)
    error_summary: Mapped[Optional[str]] = mapped_column(Text)


class TradingCalendar(Base):
    __tablename__ = "trading_calendar"
    __table_args__ = (PrimaryKeyConstraint("exchange", "calendar_date"),)

    exchange: Mapped[str] = mapped_column(String(16), nullable=False)
    calendar_date: Mapped[date] = mapped_column(Date, nullable=False)
    is_trading_day: Mapped[bool] = mapped_column(Boolean, nullable=False)
    reason: Mapped[Optional[str]] = mapped_column(String(128))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)


class Strategy(Base):
    __tablename__ = "strategies"

    strategy_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    version: Mapped[str] = mapped_column(String(64), nullable=False)
    params_json: Mapped[Dict[str, Any]] = mapped_column(JSON, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class DataQuarantine(Base):
    __tablename__ = "data_quarantine"

    quarantine_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source_table: Mapped[str] = mapped_column(String(64), nullable=False)
    source_pk_or_batch: Mapped[str] = mapped_column(String(128), nullable=False)
    raw_payload_json: Mapped[Dict[str, Any]] = mapped_column(JSON, nullable=False)
    violated_rule: Mapped[str] = mapped_column(String(64), nullable=False)
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    resolution: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    resolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    notes: Mapped[Optional[str]] = mapped_column(Text)


class IntradayIndicator(Base):
    __tablename__ = "intraday_indicators"
    __table_args__ = (PrimaryKeyConstraint("market", "symbol", "indicator_name"),)

    market: Mapped[str] = mapped_column(String(16), nullable=False)
    symbol: Mapped[str] = mapped_column(String(16), nullable=False)
    indicator_name: Mapped[str] = mapped_column(String(64), nullable=False)
    value: Mapped[float] = mapped_column(Numeric(18, 8), nullable=False)
    sample_size: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_updated_at: Mapped[date] = mapped_column(Date, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)


class IntradayTrade(Base):
    __tablename__ = "intraday_trades"

    trade_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    market: Mapped[str] = mapped_column(String(16), nullable=False)
    symbol: Mapped[str] = mapped_column(String(16), nullable=False)
    entry_date: Mapped[date] = mapped_column(Date, nullable=False)
    entry_price: Mapped[float] = mapped_column(Numeric(18, 4), nullable=False)
    exit_date: Mapped[Optional[date]] = mapped_column(Date)
    exit_price: Mapped[Optional[float]] = mapped_column(Numeric(18, 4))
    shares: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="open")  # open, closed
    profit_loss: Mapped[Optional[float]] = mapped_column(Numeric(18, 4))
    notes: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)


class IntradaySnapshot(Base):
    __tablename__ = "intraday_snapshots"
    __table_args__ = (PrimaryKeyConstraint("market", "symbol", "trading_date", "snapshot_time"),)

    market: Mapped[str] = mapped_column(String(16), nullable=False)
    symbol: Mapped[str] = mapped_column(String(16), nullable=False)
    trading_date: Mapped[date] = mapped_column(Date, nullable=False)
    snapshot_time: Mapped[str] = mapped_column(String(16), nullable=False)  # e.g., "12:00"
    cumulative_volume: Mapped[float] = mapped_column(Numeric(20, 0), nullable=False)
    last_price: Mapped[float] = mapped_column(Numeric(18, 4), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)


class MinuteBar(Base):
    """五分鐘聚合 K 線，由 1m 原始資料聚合而成，用於精確回測進出場模擬。"""
    __tablename__ = "minute_bars"
    __table_args__ = (PrimaryKeyConstraint("market", "symbol", "trading_date", "bar_time"),)

    market: Mapped[str] = mapped_column(String(16), nullable=False)
    symbol: Mapped[str] = mapped_column(String(16), nullable=False)
    trading_date: Mapped[date] = mapped_column(Date, nullable=False)
    bar_time: Mapped[str] = mapped_column(String(8), nullable=False)  # e.g., "09:05"
    open: Mapped[float] = mapped_column(Numeric(18, 4), nullable=False)
    high: Mapped[float] = mapped_column(Numeric(18, 4), nullable=False)
    low: Mapped[float] = mapped_column(Numeric(18, 4), nullable=False)
    close: Mapped[float] = mapped_column(Numeric(18, 4), nullable=False)
    volume: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    source: Mapped[Optional[str]] = mapped_column(String(64))
