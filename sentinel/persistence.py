from __future__ import annotations

import hashlib
import json
from datetime import date, datetime
from typing import Any, Dict, List, Optional, Sequence, Union

import pandas as pd
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from sentinel.indicators import INDICATOR_SPECS
from sentinel.models import (
    DailyPrice,
    DailyPrice3D,
    DailyPrice47D,
    DataQuarantine,
    JobRun,
    ScanResult,
    Stock,
    Strategy,
    TechnicalIndicator,
    TradingCalendar,
)

DateLike = Union[str, date, datetime, pd.Timestamp]

DEFAULT_JOB_NAME = "daily_scan"
DEFAULT_STRATEGY_ID = "mvp_ma_crossover"
DEFAULT_STRATEGY_VERSION = "1.0.0"
DEFAULT_INDICATOR_VERSION = "v1"


def start_job_run(engine: Engine, run_id: str, job_name: str = DEFAULT_JOB_NAME) -> None:
    with Session(engine) as session:
        _upsert_rows(
            session=session,
            table=JobRun.__table__,
            rows=[
                {
                    "run_id": run_id,
                    "job_name": job_name,
                    "start_time": datetime.utcnow(),
                    "status": "running",
                    "rows_in": 0,
                    "rows_out": 0,
                    "error_summary": None,
                }
            ],
            conflict_columns=["run_id"],
            update_columns=[
                "job_name",
                "start_time",
                "status",
                "rows_in",
                "rows_out",
                "error_summary",
            ],
        )
        session.commit()


def finish_job_run(
    engine: Engine,
    run_id: str,
    status: str,
    rows_in: Optional[int] = None,
    rows_out: Optional[int] = None,
    error_summary: Optional[str] = None,
) -> None:
    with Session(engine) as session:
        _upsert_rows(
            session=session,
            table=JobRun.__table__,
            rows=[
                {
                    "run_id": run_id,
                    "job_name": DEFAULT_JOB_NAME,
                    "start_time": datetime.utcnow(),
                    "end_time": datetime.utcnow(),
                    "status": status,
                    "rows_in": rows_in,
                    "rows_out": rows_out,
                    "error_summary": error_summary,
                }
            ],
            conflict_columns=["run_id"],
            update_columns=["end_time", "status", "rows_in", "rows_out", "error_summary"],
        )
        session.commit()


def persist_pipeline_results(
    engine: Engine,
    prices: pd.DataFrame,
    indicators: pd.DataFrame,
    scan_results: pd.DataFrame,
    trading_calendar: pd.DataFrame,
    data_quarantine: Optional[pd.DataFrame],
    run_id: str,
    trading_date: DateLike,
    data_version: str,
    strategy_definitions: Optional[Sequence[Dict[str, Any]]] = None,
) -> Dict[str, int]:
    with Session(engine) as session:
        persisted_counts = {
            "stocks": upsert_stocks(session, prices),
            "daily_prices": upsert_daily_prices(session, prices, data_version=data_version),
            "technical_indicators": upsert_technical_indicators(session, indicators, prices),
            "trading_calendar": upsert_trading_calendar(session, trading_calendar),
            "data_quarantine": insert_data_quarantine(session, data_quarantine, run_id=run_id),
        }
        persisted_counts["strategies"] = upsert_strategy_definitions(session, strategy_definitions)
        persisted_counts["scan_results"] = upsert_scan_results(
            session,
            scan_results=scan_results,
            run_id=run_id,
            trading_date=trading_date,
            data_version=data_version,
        )
        # Incrementally update aggregated bars for each market in this batch
        for market in prices["market"].unique():
            update_aggregated_bars(session, str(market), trading_date, prices)
        session.commit()
        return persisted_counts


def insert_data_quarantine(
    session: Session, quarantined_rows: Optional[pd.DataFrame], run_id: str
) -> int:
    if quarantined_rows is None or quarantined_rows.empty:
        return 0

    rows = []
    for row in quarantined_rows.to_dict(orient="records"):
        trading_date = (
            _to_date(row["trading_date"]) if row.get("trading_date") is not None else None
        )
        rows.append(
            DataQuarantine(
                source_table="daily_prices",
                source_pk_or_batch=_build_quarantine_source_pk(
                    run_id=run_id,
                    market=row.get("market"),
                    symbol=row.get("symbol"),
                    trading_date=trading_date,
                ),
                raw_payload_json={key: _to_jsonable(value) for key, value in row.items()},
                violated_rule=str(row.get("violated_rule") or "unknown"),
                detected_at=datetime.utcnow(),
                resolution="pending",
                resolved_at=None,
                notes=None,
            )
        )

    session.add_all(rows)
    session.flush()
    return len(rows)


def upsert_stocks(session: Session, prices: pd.DataFrame) -> int:
    if prices.empty:
        return 0

    stock_frame = prices[["symbol", "name", "market"]].copy()
    stock_frame["industry"] = None
    stock_frame["list_status"] = "active"
    rows = _build_stock_rows(stock_frame)
    # industry 由 stock master sync 負責，price sync 不覆蓋
    _upsert_stock_rows(session, rows, update_columns=["name", "list_status", "updated_at"])
    return len(rows)


def upsert_stock_master_rows(session: Session, stock_master: pd.DataFrame) -> int:
    if stock_master.empty:
        return 0

    stock_frame = stock_master[["symbol", "name", "market", "industry", "list_status"]].copy()
    rows = _build_stock_rows(stock_frame)
    _upsert_stock_rows(session, rows)
    return len(rows)


def _build_stock_rows(stock_frame: pd.DataFrame) -> List[Dict[str, Any]]:
    deduped = (
        stock_frame.drop_duplicates(subset=["market", "symbol"], keep="last")
        .sort_values(["market", "symbol"])
        .reset_index(drop=True)
    )
    return [
        {
            "market": row["market"],
            "symbol": row["symbol"],
            "name": row.get("name"),
            "industry": row.get("industry"),
            "list_status": row.get("list_status") or "active",
            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow(),
        }
        for row in deduped.to_dict(orient="records")
    ]


def _upsert_stock_rows(
    session: Session,
    rows: List[Dict[str, Any]],
    update_columns: Optional[Sequence[str]] = None,
) -> None:
    _upsert_rows(
        session=session,
        table=Stock.__table__,
        rows=rows,
        conflict_columns=["market", "symbol"],
        update_columns=update_columns or ["name", "industry", "list_status", "updated_at"],
    )


def upsert_daily_prices(session: Session, prices: pd.DataFrame, data_version: str) -> int:
    if prices.empty:
        return 0

    frame = prices[
        ["market", "symbol", "trading_date", "open", "high", "low", "close", "volume", "turnover"]
    ].copy()
    frame["trading_date"] = pd.to_datetime(frame["trading_date"]).dt.date
    for column in ("open", "high", "low", "close"):
        frame[column] = frame[column].astype(float)
    frame["volume"] = frame["volume"].astype(int)
    turnover = pd.to_numeric(frame["turnover"])
    # 用 list comprehension 而非 astype("Int64")：driver 需要原生 int/None，pd.NA 無法綁定
    frame["turnover"] = [int(v) if pd.notna(v) else None for v in turnover]
    frame["adjusted_close"] = frame["close"]
    frame["data_version"] = data_version
    frame["updated_at"] = datetime.utcnow()
    rows = frame.to_dict(orient="records")

    _upsert_rows(
        session=session,
        table=DailyPrice.__table__,
        rows=rows,
        conflict_columns=["market", "symbol", "trading_date"],
        update_columns=[
            "open",
            "high",
            "low",
            "close",
            "volume",
            "turnover",
            "adjusted_close",
            "data_version",
            "updated_at",
        ],
    )
    return len(rows)


def upsert_technical_indicators(
    session: Session, indicators: pd.DataFrame, prices: pd.DataFrame
) -> int:
    if indicators.empty or prices.empty:
        return 0

    keys = prices[["market", "symbol", "trading_date"]].copy()
    keys["trading_date"] = pd.to_datetime(keys["trading_date"]).dt.date
    keys = keys.drop_duplicates()

    filtered = indicators.copy()
    filtered["trading_date"] = pd.to_datetime(filtered["trading_date"]).dt.date
    filtered = filtered.merge(keys, on=["market", "symbol", "trading_date"], how="inner")
    if filtered.empty:
        return 0

    now = datetime.utcnow()
    rows: List[Dict[str, Any]] = []
    for column_name, spec in INDICATOR_SPECS.items():
        if column_name not in filtered.columns:
            continue
        subset = filtered.loc[
            filtered[column_name].notna(), ["market", "symbol", "trading_date", column_name]
        ]
        if subset.empty:
            continue
        chunk = pd.DataFrame(
            {
                "market": subset["market"],
                "symbol": subset["symbol"],
                "trading_date": subset["trading_date"],
                "indicator_name": str(spec["indicator_name"]),
                "params_hash": _hash_indicator_params(spec["params"]),
                "calc_version": DEFAULT_INDICATOR_VERSION,
                "value": subset[column_name].astype(float),
                "source_field": str(spec["source_field"]),
                "updated_at": now,
            }
        )
        rows.extend(chunk.to_dict(orient="records"))

    _upsert_rows(
        session=session,
        table=TechnicalIndicator.__table__,
        rows=rows,
        conflict_columns=[
            "market",
            "symbol",
            "trading_date",
            "indicator_name",
            "params_hash",
            "calc_version",
        ],
        update_columns=["value", "source_field", "updated_at"],
    )
    return len(rows)


def upsert_strategy_definitions(
    session: Session,
    strategy_definitions: Optional[Sequence[Dict[str, Any]]] = None,
) -> int:
    active_strategies = list(strategy_definitions or [_default_strategy_definition()])
    _upsert_rows(
        session=session,
        table=Strategy.__table__,
        rows=[
            {
                "strategy_id": strategy["strategy_id"],
                "name": strategy["name"],
                "version": strategy.get("version", DEFAULT_STRATEGY_VERSION),
                "params_json": strategy.get("params_json", {}),
                "description": strategy.get("description"),
                "is_active": bool(strategy.get("is_active", True)),
            }
            for strategy in active_strategies
        ],
        conflict_columns=["strategy_id"],
        update_columns=["name", "version", "params_json", "description", "is_active"],
    )
    return len(active_strategies)


def upsert_scan_results(
    session: Session,
    scan_results: pd.DataFrame,
    run_id: str,
    trading_date: DateLike,
    data_version: str,
) -> int:
    if scan_results.empty:
        return 0

    rows = []
    for row in scan_results.to_dict(orient="records"):
        rows.append(
            {
                "run_id": run_id,
                "market": row["market"],
                "symbol": row["symbol"],
                "strategy_id": row.get("strategy_id", DEFAULT_STRATEGY_ID),
                "trading_date": _to_date(row.get("trading_date", trading_date)),
                "score": float(row.get("score", 1.0)),
                "signals_json": {
                    **((_to_jsonable(row.get("signals_json")) or {})),
                    **({"direction": row["direction"]} if row.get("direction") else {}),
                },
                "data_version": data_version,
                "created_at": datetime.utcnow(),
            }
        )

    _upsert_rows(
        session=session,
        table=ScanResult.__table__,
        rows=rows,
        conflict_columns=["run_id", "market", "symbol", "strategy_id"],
        update_columns=["trading_date", "score", "signals_json", "data_version", "created_at"],
    )
    return len(rows)


def _default_strategy_definition() -> Dict[str, Any]:
    return {
        "strategy_id": DEFAULT_STRATEGY_ID,
        "name": "MVP MA Crossover",
        "version": DEFAULT_STRATEGY_VERSION,
        "params_json": {
            "conditions": [
                {"field": "close", "operator": ">", "target": "ma5"},
                {"field": "ma5", "operator": ">", "target": "ma20"},
            ]
        },
        "description": "close > MA5 and MA5 > MA20",
        "is_active": True,
    }


def upsert_trading_calendar(session: Session, trading_calendar: pd.DataFrame) -> int:
    if trading_calendar.empty:
        return 0

    frame = trading_calendar[["exchange", "calendar_date", "is_trading_day", "reason"]].copy()
    frame["calendar_date"] = pd.to_datetime(frame["calendar_date"]).dt.date
    frame["is_trading_day"] = frame["is_trading_day"].astype(bool)
    frame["updated_at"] = datetime.utcnow()
    rows = frame.to_dict(orient="records")

    _upsert_rows(
        session=session,
        table=TradingCalendar.__table__,
        rows=rows,
        conflict_columns=["exchange", "calendar_date"],
        update_columns=["is_trading_day", "reason", "updated_at"],
    )
    return len(rows)


def _upsert_rows(
    session: Session,
    table,
    rows: Sequence[Dict[str, Any]],
    conflict_columns: Sequence[str],
    update_columns: Sequence[str],
) -> None:
    if not rows:
        return

    dialect_name = session.bind.dialect.name

    if dialect_name == "sqlite":
        # SQLite has a limit on the number of parameters (usually 999).
        # We chunk the rows to avoid "too many SQL variables" error.
        chunk_size = max(1, 900 // len(table.columns))
        for i in range(0, len(rows), chunk_size):
            chunk = list(rows[i : i + chunk_size])
            insert_stmt = sqlite_insert(table).values(chunk)
            excluded = insert_stmt.excluded
            stmt = insert_stmt.on_conflict_do_update(
                index_elements=list(conflict_columns),
                set_={column: getattr(excluded, column) for column in update_columns},
            )
            session.execute(stmt)
        return

    if dialect_name == "postgresql":
        insert_stmt = postgresql_insert(table).values(list(rows))
        excluded = insert_stmt.excluded
        stmt = insert_stmt.on_conflict_do_update(
            index_elements=list(conflict_columns),
            set_={column: getattr(excluded, column) for column in update_columns},
        )
        session.execute(stmt)
        return

    model_class = table_to_model(table.name)
    for row in rows:
        session.merge(model_class(**row))


def table_to_model(table_name: str):
    return {
        "stocks": Stock,
        "daily_prices": DailyPrice,
        "daily_prices_3d": DailyPrice3D,
        "daily_prices_47d": DailyPrice47D,
        "technical_indicators": TechnicalIndicator,
        "scan_results": ScanResult,
        "job_runs": JobRun,
        "strategies": Strategy,
        "trading_calendar": TradingCalendar,
        "data_quarantine": DataQuarantine,
    }[table_name]


# ---------------------------------------------------------------------------
# Aggregated bar helpers
# ---------------------------------------------------------------------------


def _get_trading_day_sequence(session: Session, market: str) -> pd.DataFrame:
    """Return DataFrame with columns [calendar_date, seq_idx] for all trading days of market."""
    from sqlalchemy import select

    stmt = (
        select(TradingCalendar.calendar_date)
        .where(TradingCalendar.exchange == market, TradingCalendar.is_trading_day.is_(True))
        .order_by(TradingCalendar.calendar_date)
    )
    rows = session.execute(stmt).fetchall()
    dates = [r[0] for r in rows]
    return pd.DataFrame({"calendar_date": pd.to_datetime(dates).date, "seq_idx": range(len(dates))})


def _aggregate_ohlcv(group: pd.DataFrame) -> Dict[str, Any]:
    group = group.sort_values("trading_date")
    return {
        "open": float(group["open"].iloc[0]),
        "high": float(group["high"].max()),
        "low": float(group["low"].min()),
        "close": float(group["close"].iloc[-1]),
        "volume": int(group["volume"].sum()),
        "adjusted_close": float(group["close"].iloc[-1]),
        "period_end_date": group["trading_date"].iloc[-1],
        "updated_at": datetime.utcnow(),
    }


def backfill_aggregated_bars(session: Session, prices: pd.DataFrame) -> Dict[str, int]:
    """Backfill daily_prices_3d and daily_prices_47d from a full prices DataFrame.

    prices must have columns: market, symbol, trading_date, open, high, low, close, volume.
    Returns counts of rows upserted for each table.
    """
    if prices.empty:
        return {"daily_prices_3d": 0, "daily_prices_47d": 0}

    prices = prices.copy()
    prices["trading_date"] = pd.to_datetime(prices["trading_date"]).dt.date

    counts: Dict[str, int] = {}
    for n, table, model_table in [
        (3, DailyPrice3D.__table__, "daily_prices_3d"),
        (47, DailyPrice47D.__table__, "daily_prices_47d"),
    ]:
        rows: List[Dict[str, Any]] = []
        for market, market_prices in prices.groupby("market"):
            seq = _get_trading_day_sequence(session, str(market))
            merged = market_prices.merge(
                seq, left_on="trading_date", right_on="calendar_date", how="inner"
            )
            merged["period_idx"] = merged["seq_idx"] // n

            for (symbol, period_idx), grp in merged.groupby(["symbol", "period_idx"]):
                if len(grp) < n:
                    continue  # incomplete block — skip
                agg = _aggregate_ohlcv(grp)
                rows.append(
                    {
                        "market": str(market),
                        "symbol": str(symbol),
                        **agg,
                    }
                )

        _upsert_rows(
            session=session,
            table=table,
            rows=rows,
            conflict_columns=["market", "symbol", "period_end_date"],
            update_columns=[
                "open",
                "high",
                "low",
                "close",
                "volume",
                "adjusted_close",
                "updated_at",
            ],
        )
        counts[model_table] = len(rows)

    return counts


def update_aggregated_bars(
    session: Session, market: str, trading_date: DateLike, prices: pd.DataFrame
) -> None:
    """Incrementally append a completed 3D or 47D bar when the trading_date closes a block.

    Called after upsert_daily_prices for each new trading day.
    """
    trading_date = _to_date(trading_date)
    seq = _get_trading_day_sequence(session, market)
    today_row = seq[seq["calendar_date"] == trading_date]
    if today_row.empty:
        return

    today_idx = int(today_row["seq_idx"].iloc[0])

    for n, table in [(3, DailyPrice3D.__table__), (47, DailyPrice47D.__table__)]:
        if (today_idx + 1) % n != 0:
            continue  # this trading_date does not close an N-day block

        # Find the first date of this block
        block_start_idx = today_idx - (n - 1)
        block_dates = set(
            seq[seq["seq_idx"].between(block_start_idx, today_idx)]["calendar_date"].tolist()
        )

        symbol_prices = prices[
            (prices["market"] == market)
            & (prices["trading_date"].apply(_to_date).isin(block_dates))
        ].copy()
        if symbol_prices.empty:
            continue

        rows: List[Dict[str, Any]] = []
        for symbol, grp in symbol_prices.groupby("symbol"):
            if len(grp) < n:
                continue
            agg = _aggregate_ohlcv(grp)
            rows.append({"market": market, "symbol": str(symbol), **agg})

        _upsert_rows(
            session=session,
            table=table,
            rows=rows,
            conflict_columns=["market", "symbol", "period_end_date"],
            update_columns=[
                "open",
                "high",
                "low",
                "close",
                "volume",
                "adjusted_close",
                "updated_at",
            ],
        )


def _hash_indicator_params(params: Dict[str, Any]) -> str:
    serialized = json.dumps(params, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _to_date(value: DateLike) -> date:
    return pd.to_datetime(value).date()


def _build_quarantine_source_pk(run_id: str, market: Any, symbol: Any, trading_date: Any) -> str:
    date_text = trading_date.isoformat() if trading_date is not None else "unknown-date"
    return "{0}:{1}:{2}:{3}".format(
        run_id, market or "unknown-market", symbol or "unknown-symbol", date_text
    )


def _to_jsonable(value: Any) -> Any:
    if isinstance(value, list):
        return [_to_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _to_jsonable(item) for key, item in value.items()}
    if pd.isna(value):
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)
