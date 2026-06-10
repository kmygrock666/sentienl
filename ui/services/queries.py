from __future__ import annotations

import json as _json
from datetime import date, timedelta
from pathlib import Path as _Path
from typing import Optional

import pandas as pd
from sqlalchemy import func
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

def _strategy_direction_map() -> dict[str, str]:
    """從 strategies.json 建立 strategy_id → direction 的對照表。"""
    cfg = _Path(__file__).parent.parent.parent / "config" / "strategies.json"
    try:
        data = _json.loads(cfg.read_text(encoding="utf-8"))
        m: dict[str, str] = {}
        for s in data.get("long_strategies", []):
            m[s["strategy_id"]] = "long"
        for s in data.get("short_strategies", []):
            m[s["strategy_id"]] = "short"
        return m
    except Exception:
        return {}

_DIR_MAP: dict[str, str] = _strategy_direction_map()

from sentinel.models import (
    DailyPrice,
    DataQuarantine,
    IntradayTrade,
    JobRun,
    ScanResult,
    Stock,
    TechnicalIndicator,
)


def get_latest_job_runs(engine: Engine, limit: int = 10) -> pd.DataFrame:
    with Session(engine) as s:
        rows = (
            s.query(JobRun)
            .order_by(JobRun.start_time.desc())
            .limit(limit)
            .all()
        )
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(
        [
            {
                "run_id": r.run_id,
                "job_name": r.job_name,
                "status": r.status,
                "start_time": r.start_time,
                "end_time": r.end_time,
                "rows_in": r.rows_in,
                "rows_out": r.rows_out,
                "error_summary": r.error_summary,
            }
            for r in rows
        ]
    )


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
        [{"market": r.market, "latest_date": r.latest_date, "symbol_count": r.symbol_count}
         for r in rows]
    )


def get_scan_results(
    engine: Engine,
    trading_date: Optional[date] = None,
    market: Optional[str] = None,
    strategy_id: Optional[str] = None,
    direction: Optional[str] = None,
    min_score: float = 0.0,
    limit: int = 500,
) -> pd.DataFrame:
    with Session(engine) as s:
        q = (
            s.query(
                ScanResult.run_id,
                ScanResult.market,
                ScanResult.symbol,
                ScanResult.strategy_id,
                ScanResult.trading_date,
                ScanResult.score,
                ScanResult.signals_json,
                Stock.name,
                Stock.industry,
                DailyPrice.close,
            )
            .outerjoin(Stock, (Stock.market == ScanResult.market) & (Stock.symbol == ScanResult.symbol))
            .outerjoin(
                DailyPrice,
                (DailyPrice.market == ScanResult.market)
                & (DailyPrice.symbol == ScanResult.symbol)
                & (DailyPrice.trading_date == ScanResult.trading_date),
            )
        )
        if trading_date:
            q = q.filter(ScanResult.trading_date == trading_date)
        if market:
            q = q.filter(ScanResult.market == market)
        if strategy_id:
            q = q.filter(ScanResult.strategy_id == strategy_id)
        if direction:
            q = q.filter(ScanResult.signals_json["direction"].astext == direction)
        if min_score > 0:
            q = q.filter(ScanResult.score >= min_score)
        q = q.order_by(ScanResult.trading_date.desc(), ScanResult.score.desc()).limit(limit)
        rows = q.all()

    if not rows:
        return pd.DataFrame()

    records = []
    for r in rows:
        sig = r.signals_json if isinstance(r.signals_json, dict) else {}
        records.append({
            "trading_date": r.trading_date,
            "market": r.market,
            "symbol": r.symbol,
            "name": r.name or "",
            "industry": r.industry or "",
            "strategy_id": r.strategy_id,
            "direction": sig.get("direction", "") or _DIR_MAP.get(r.strategy_id, ""),
            "score": float(r.score) if r.score is not None else None,
            "close": float(r.close) if r.close is not None else None,
            "signals_json": r.signals_json,
        })

    return pd.DataFrame(records)


def get_available_scan_dates(engine: Engine, limit: int = 60) -> list[date]:
    with Session(engine) as s:
        rows = (
            s.query(ScanResult.trading_date.distinct())
            .order_by(ScanResult.trading_date.desc())
            .limit(limit)
            .all()
        )
    return [r[0] for r in rows]


def get_available_strategies(engine: Engine) -> list[str]:
    with Session(engine) as s:
        rows = s.query(ScanResult.strategy_id.distinct()).all()
    return sorted([r[0] for r in rows])


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
    df = pd.DataFrame([{"trading_date": r.trading_date, "indicator_name": r.indicator_name, "value": float(r.value)} for r in rows])
    return df.pivot(index="trading_date", columns="indicator_name", values="value").reset_index()


def get_stock_scan_history(
    engine: Engine, symbol: str, market: str, limit: int = 20
) -> pd.DataFrame:
    with Session(engine) as s:
        rows = (
            s.query(ScanResult)
            .filter(ScanResult.symbol == symbol, ScanResult.market == market)
            .order_by(ScanResult.trading_date.desc())
            .limit(limit)
            .all()
        )
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(
        [
            {
                "trading_date": r.trading_date,
                "strategy_id": r.strategy_id,
                "score": float(r.score) if r.score is not None else None,
                "signals_json": r.signals_json,
            }
            for r in rows
        ]
    )


def get_quarantine_summary(engine: Engine) -> dict:
    with Session(engine) as s:
        total = s.query(func.count(DataQuarantine.quarantine_id)).scalar() or 0
        pending = (
            s.query(func.count(DataQuarantine.quarantine_id))
            .filter(DataQuarantine.resolution == "pending")
            .scalar()
            or 0
        )
        recent = (
            s.query(DataQuarantine)
            .order_by(DataQuarantine.detected_at.desc())
            .limit(10)
            .all()
        )
    recent_df = pd.DataFrame(
        [
            {
                "detected_at": r.detected_at,
                "source_table": r.source_table,
                "violated_rule": r.violated_rule,
                "resolution": r.resolution,
            }
            for r in recent
        ]
    ) if recent else pd.DataFrame()
    return {"total": total, "pending": pending, "recent": recent_df}


def get_intraday_trades(engine: Engine, status: Optional[str] = None) -> pd.DataFrame:
    with Session(engine) as s:
        q = (
            s.query(IntradayTrade, Stock.name)
            .outerjoin(Stock, (Stock.market == IntradayTrade.market) & (Stock.symbol == IntradayTrade.symbol))
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
                "出場價": float(r.IntradayTrade.exit_price) if r.IntradayTrade.exit_price is not None else None,
                "狀態": r.IntradayTrade.status,
                "損益": float(r.IntradayTrade.profit_loss) if r.IntradayTrade.profit_loss is not None else None,
                "備註": r.IntradayTrade.notes or "",
            }
            for r in rows
        ]
    )


def get_latest_price_date(engine: Engine) -> Optional[date]:
    with Session(engine) as s:
        return s.query(func.max(DailyPrice.trading_date)).scalar()


def get_latest_scan_summary(engine: Engine) -> dict:
    with Session(engine) as s:
        latest_date = s.query(func.max(ScanResult.trading_date)).scalar()
        if not latest_date:
            return {"latest_date": None, "total_hits": 0, "by_strategy": pd.DataFrame()}
        total = (
            s.query(func.count())
            .select_from(ScanResult)
            .filter(ScanResult.trading_date == latest_date)
            .scalar()
            or 0
        )
        by_strategy = (
            s.query(
                ScanResult.strategy_id,
                func.count().label("hits"),
            )
            .filter(ScanResult.trading_date == latest_date)
            .group_by(ScanResult.strategy_id)
            .order_by(func.count().desc())
            .all()
        )
    by_strategy_df = pd.DataFrame(
        [{"strategy_id": r.strategy_id, "hits": r.hits} for r in by_strategy]
    ) if by_strategy else pd.DataFrame()
    return {"latest_date": latest_date, "total_hits": total, "by_strategy": by_strategy_df}
