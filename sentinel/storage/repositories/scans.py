from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Optional

import pandas as pd
from sqlalchemy import func
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from sentinel.models import DailyPrice, ScanResult, Stock


def _strategy_direction_map() -> dict[str, str]:
    """從 strategies.json 建立 strategy_id → direction 的對照表。"""
    # 以 repo 根目錄定位設定檔，不受呼叫端 cwd 影響
    cfg = Path(__file__).resolve().parents[3] / "config" / "strategies.json"
    try:
        data = json.loads(cfg.read_text(encoding="utf-8"))
        m: dict[str, str] = {}
        for s in data.get("long_strategies", []):
            m[s["strategy_id"]] = "long"
        for s in data.get("short_strategies", []):
            m[s["strategy_id"]] = "short"
        return m
    except Exception:
        return {}


_DIR_MAP: dict[str, str] = _strategy_direction_map()


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
            .outerjoin(
                Stock, (Stock.market == ScanResult.market) & (Stock.symbol == ScanResult.symbol)
            )
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
        records.append(
            {
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
            }
        )

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
    by_strategy_df = (
        pd.DataFrame([{"strategy_id": r.strategy_id, "hits": r.hits} for r in by_strategy])
        if by_strategy
        else pd.DataFrame()
    )
    return {"latest_date": latest_date, "total_hits": total, "by_strategy": by_strategy_df}
