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

from sentinel.config import Settings
from sentinel.models import (
    DailyPrice,
    DataQuarantine,
    InstitutionalFlow,
    IntradayTrade,
    JobRun,
    ScanResult,
    Stock,
    TechnicalIndicator,
)
from sentinel.storage import load_price_dataset

_PRICE_FRAME_COLUMNS = [
    "market",
    "symbol",
    "trading_date",
    "open",
    "high",
    "low",
    "close",
    "volume",
]


def load_symbol_prices(symbol: str, days: int = 120, market: str | None = None) -> pd.DataFrame:
    """從 CSV 價格資料集載入單一個股最近 N 個交易日（昇冪）。找不到回空 frame。

    Args:
        symbol: 股票代號（字串比對）。
        days:   最多取最近幾個交易日，預設 120。
        market: 若指定（"TWSE" 或 "TPEX"），只回傳該市場的列；
                None 則不過濾市場（注意：相同代號可能同時出現在 TWSE 與
                TPEX，會造成 (symbol, trading_date) 重複，呼叫端應傳入
                market 以避免碰撞）。
    """
    dataset = load_price_dataset(Settings().price_dataset_path)
    if dataset.empty:
        return pd.DataFrame(columns=_PRICE_FRAME_COLUMNS)
    matched = dataset.loc[dataset["symbol"].astype(str) == symbol]
    if market is not None:
        matched = matched.loc[matched["market"] == market]
    if matched.empty:
        return pd.DataFrame(columns=_PRICE_FRAME_COLUMNS)
    return matched.sort_values("trading_date").tail(days).reset_index(drop=True)


def get_latest_job_runs(engine: Engine, limit: int = 10) -> pd.DataFrame:
    with Session(engine) as s:
        rows = s.query(JobRun).order_by(JobRun.start_time.desc()).limit(limit).all()
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
        [
            {"market": r.market, "latest_date": r.latest_date, "symbol_count": r.symbol_count}
            for r in rows
        ]
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
    df = pd.DataFrame(
        [
            {
                "trading_date": r.trading_date,
                "indicator_name": r.indicator_name,
                "value": float(r.value),
            }
            for r in rows
        ]
    )
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
        recent = s.query(DataQuarantine).order_by(DataQuarantine.detected_at.desc()).limit(10).all()
    recent_df = (
        pd.DataFrame(
            [
                {
                    "detected_at": r.detected_at,
                    "source_table": r.source_table,
                    "violated_rule": r.violated_rule,
                    "resolution": r.resolution,
                }
                for r in recent
            ]
        )
        if recent
        else pd.DataFrame()
    )
    return {"total": total, "pending": pending, "recent": recent_df}


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


_INSTITUTIONAL_COLUMNS = ["日期", "外資", "投信", "自營商", "合計"]


def get_institutional_flow(
    engine: Engine, market: str, symbol: str, days: int = 10
) -> pd.DataFrame:
    """近 N 個交易日的法人買賣超。欄位：日期, 外資, 投信, 自營商, 合計（張）。"""

    def _to_lots(value: int | None) -> int | None:
        return int(value / 1000) if value is not None else None

    with Session(engine) as s:
        rows = (
            s.query(InstitutionalFlow)
            .filter(InstitutionalFlow.market == market, InstitutionalFlow.symbol == symbol)
            .order_by(InstitutionalFlow.trading_date.desc())
            .limit(days)
            .all()
        )
    if not rows:
        return pd.DataFrame(columns=_INSTITUTIONAL_COLUMNS)
    df = pd.DataFrame(
        [
            {
                "日期": r.trading_date,
                "外資": _to_lots(r.foreign_net),
                "投信": _to_lots(r.investment_trust_net),
                "自營商": _to_lots(r.dealer_net),
                "合計": _to_lots(r.total_net),
            }
            for r in rows
        ]
    )
    # 缺值保持為 NA（避免 None 混入時整欄被轉為 float）
    for col in _INSTITUTIONAL_COLUMNS[1:]:
        df[col] = df[col].astype("Int64")
    return df


_NET_COLUMN_WHITELIST = frozenset(
    {"foreign_net", "investment_trust_net", "dealer_net", "total_net"}
)
_RANKING_COLUMNS = ["市場", "代號", "名稱", "買賣超(張)"]
_STREAK_COLUMNS = ["市場", "代號", "名稱", "連買天數", "期間累計(張)"]


def get_institutional_dates(engine: Engine, limit: int = 30) -> list[date]:
    """institutional_flows 中存在資料的交易日（新→舊，最多 limit 個）。"""
    with Session(engine) as s:
        rows = (
            s.query(InstitutionalFlow.trading_date.distinct())
            .order_by(InstitutionalFlow.trading_date.desc())
            .limit(limit)
            .all()
        )
    return [r[0] for r in rows]


def get_institutional_ranking(
    engine: Engine,
    trading_date: date,
    net_column: str,
    market: str | None = None,
    ascending: bool = False,
    limit: int = 20,
) -> pd.DataFrame:
    """單日法人買賣超排行。欄位：市場, 代號, 名稱, 買賣超(張)。

    買超排行（ascending=False）只收正值、賣超排行只收負值，
    避免排行尾端出現反向值。net_column 必須在白名單內（防注入、防打錯）。
    """
    if net_column not in _NET_COLUMN_WHITELIST:
        raise ValueError(
            f"net_column 必須是 {sorted(_NET_COLUMN_WHITELIST)} 之一，收到：{net_column!r}"
        )
    net_col = getattr(InstitutionalFlow, net_column)
    with Session(engine) as s:
        q = (
            s.query(
                InstitutionalFlow.market,
                InstitutionalFlow.symbol,
                Stock.name,
                net_col.label("net"),
            )
            .outerjoin(
                Stock,
                (Stock.market == InstitutionalFlow.market)
                & (Stock.symbol == InstitutionalFlow.symbol),
            )
            .filter(InstitutionalFlow.trading_date == trading_date)
        )
        if market:
            q = q.filter(InstitutionalFlow.market == market)
        if ascending:
            q = q.filter(net_col < 0).order_by(net_col.asc())
        else:
            q = q.filter(net_col > 0).order_by(net_col.desc())
        rows = q.limit(limit).all()
    if not rows:
        return pd.DataFrame(columns=_RANKING_COLUMNS)
    return pd.DataFrame(
        [
            {
                "市場": r.market,
                "代號": r.symbol,
                "名稱": r.name or "",
                "買賣超(張)": int(r.net / 1000),
            }
            for r in rows
        ]
    )


def get_foreign_streak_ranking(
    engine: Engine,
    end_date: date,
    days: int = 10,
    market: str | None = None,
    limit: int = 20,
) -> pd.DataFrame:
    """外資連續買超天數排行（以 end_date 往回 days 個資料日計算）。

    streak 定義：從 end_date 往回、foreign_net > 0 連續的天數
    （中斷即停，缺資料日視為中斷）；只列 streak >= 2。
    期間累計 = streak 期間的 foreign_net 加總（張）。
    """
    with Session(engine) as s:
        date_rows = (
            s.query(InstitutionalFlow.trading_date.distinct())
            .filter(InstitutionalFlow.trading_date <= end_date)
            .order_by(InstitutionalFlow.trading_date.desc())
            .limit(days)
            .all()
        )
        window = [r[0] for r in date_rows]  # 新 → 舊
        if not window:
            return pd.DataFrame(columns=_STREAK_COLUMNS)
        q = (
            s.query(
                InstitutionalFlow.market,
                InstitutionalFlow.symbol,
                InstitutionalFlow.trading_date,
                InstitutionalFlow.foreign_net,
                Stock.name,
            )
            .outerjoin(
                Stock,
                (Stock.market == InstitutionalFlow.market)
                & (Stock.symbol == InstitutionalFlow.symbol),
            )
            .filter(InstitutionalFlow.trading_date.in_(window))
        )
        if market:
            q = q.filter(InstitutionalFlow.market == market)
        rows = q.all()
    if not rows:
        return pd.DataFrame(columns=_STREAK_COLUMNS)

    by_stock: dict[tuple[str, str], dict] = {}
    for r in rows:
        entry = by_stock.setdefault((r.market, r.symbol), {"name": r.name or "", "nets": {}})
        entry["nets"][r.trading_date] = r.foreign_net

    records = []
    for (mkt, symbol), entry in by_stock.items():
        streak, total = 0, 0
        for d in window:  # 從最近的資料日往回走
            net = entry["nets"].get(d)
            if net is None or net <= 0:
                break
            streak += 1
            total += net
        if streak >= 2:
            records.append(
                {
                    "市場": mkt,
                    "代號": symbol,
                    "名稱": entry["name"],
                    "連買天數": streak,
                    "期間累計(張)": int(total / 1000),
                }
            )
    if not records:
        return pd.DataFrame(columns=_STREAK_COLUMNS)
    df = pd.DataFrame(records).sort_values(
        ["連買天數", "期間累計(張)"], ascending=[False, False], kind="stable"
    )
    return df.head(limit).reset_index(drop=True)


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
    by_strategy_df = (
        pd.DataFrame([{"strategy_id": r.strategy_id, "hits": r.hits} for r in by_strategy])
        if by_strategy
        else pd.DataFrame()
    )
    return {"latest_date": latest_date, "total_hits": total, "by_strategy": by_strategy_df}
