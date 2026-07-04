"""資料同步指令：init-db、sync-calendar、sync-stocks、sync-institutional、sync-main-force。"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd
from sqlalchemy.orm import Session

from sentinel.cli.common import create_engine_with_schema, require_database_url
from sentinel.config import Settings
from sentinel.datasources.institutional import build_institutional_provider
from sentinel.datasources.main_force import (
    FinMindError,
    compute_main_force_daily,
    fetch_trading_daily_report,
)
from sentinel.datasources.official_calendar import fetch_official_trading_calendar
from sentinel.datasources.stock_master import (
    fetch_stock_master_with_diagnostics,
    load_stock_master,
    save_stock_master,
    save_stock_master_diagnostics,
    upsert_stock_master,
)
from sentinel.domain.calendar import build_trading_calendar, save_trading_calendar
from sentinel.domain.models import Stock
from sentinel.logging_utils import get_logger
from sentinel.storage.engine import create_db_engine, create_schema
from sentinel.storage.persistence import (
    upsert_institutional_flows,
    upsert_main_force_daily,
    upsert_stock_master_rows,
    upsert_trading_calendar,
)
from sentinel.utils import parse_iso_date

_logger = get_logger(__name__)


def register(subparsers: argparse._SubParsersAction) -> None:
    init_db_parser = subparsers.add_parser("init-db", help="Initialize database schema")
    init_db_parser.add_argument(
        "--database-url",
        help="SQLAlchemy database URL. Defaults to TS_DATABASE_URL from environment.",
    )
    init_db_parser.set_defaults(handler=cmd_init_db)

    calendar_parser = subparsers.add_parser(
        "sync-calendar", help="Sync trading calendar from official sources"
    )
    calendar_parser.add_argument(
        "--start-date", required=True, help="Inclusive start date in YYYY-MM-DD"
    )
    calendar_parser.add_argument(
        "--end-date", required=True, help="Inclusive end date in YYYY-MM-DD"
    )
    calendar_parser.add_argument(
        "--market",
        action="append",
        dest="markets",
        default=[],
        help="Market to sync. Repeatable.",
    )
    calendar_parser.add_argument(
        "--output-dir",
        type=Path,
        help="Override the output directory for calendar artifacts.",
    )
    calendar_parser.add_argument(
        "--database-url",
        help="SQLAlchemy database URL. Defaults to TS_DATABASE_URL from environment.",
    )
    calendar_parser.add_argument(
        "--source-mode",
        choices=["auto", "fixture", "network"],
        default="auto",
        help="Calendar source mode. 'fixture' only uses local fixture HTML files.",
    )
    calendar_parser.set_defaults(handler=cmd_sync_calendar)

    stocks_parser = subparsers.add_parser(
        "sync-stocks", help="Sync stock master from fixture sources"
    )
    stocks_parser.add_argument(
        "--market",
        action="append",
        dest="markets",
        default=[],
        help="Market to sync. Repeatable.",
    )
    stocks_parser.add_argument(
        "--dataset-path",
        type=Path,
        help="Override the canonical stock master dataset path.",
    )
    stocks_parser.add_argument(
        "--database-url",
        help="SQLAlchemy database URL. Defaults to TS_DATABASE_URL from environment.",
    )
    stocks_parser.add_argument(
        "--source-mode",
        choices=["fixture", "network", "auto"],
        default="auto",
        help="Stock master source mode. Auto prefers fixture first, then configured network URL.",
    )
    stocks_parser.add_argument(
        "--diagnostics-path",
        type=Path,
        help="Write stock master sync diagnostics JSON to this path. Defaults to outputs/stock_master/sync_diagnostics.json.",
    )
    stocks_parser.set_defaults(handler=cmd_sync_stocks)

    institutional_parser = subparsers.add_parser(
        "sync-institutional", help="Sync institutional (三大法人) net buy/sell flows for a date"
    )
    institutional_parser.add_argument("--date", required=True, help="Trading date in YYYY-MM-DD")
    institutional_parser.add_argument(
        "--market",
        action="append",
        dest="markets",
        default=[],
        help="Market to sync. Repeatable. Defaults to TWSE, TPEX.",
    )
    institutional_parser.add_argument(
        "--source-mode",
        choices=["fixture", "network", "auto"],
        default="auto",
        help="Institutional flow source mode. 'fixture' only uses local fixture CSV files.",
    )
    institutional_parser.add_argument(
        "--database-url",
        help="SQLAlchemy database URL. Defaults to TS_DATABASE_URL from environment.",
    )
    institutional_parser.set_defaults(handler=cmd_sync_institutional)

    main_force_parser = subparsers.add_parser(
        "sync-main-force",
        help="Sync 主力買賣超 (broker-branch top-N) for a symbol via FinMind (Sponsor token required)",
    )
    main_force_parser.add_argument("--symbol", required=True, help="Stock symbol (e.g. 5347)")
    main_force_parser.add_argument(
        "--start-date", required=True, help="Inclusive start date in YYYY-MM-DD"
    )
    main_force_parser.add_argument(
        "--end-date", required=True, help="Inclusive end date in YYYY-MM-DD"
    )
    main_force_parser.add_argument(
        "--top-n",
        type=int,
        default=15,
        help="Number of top buy/sell branches to aggregate. Default 15.",
    )
    main_force_parser.add_argument(
        "--market",
        help="Market (TWSE or TPEX). Auto-resolved from the stocks table when omitted.",
    )
    main_force_parser.add_argument(
        "--database-url",
        help="SQLAlchemy database URL. Defaults to TS_DATABASE_URL from environment.",
    )
    main_force_parser.set_defaults(handler=cmd_sync_main_force)


def cmd_init_db(
    args: argparse.Namespace, *, settings: Settings, parser: argparse.ArgumentParser
) -> int:
    database_url = require_database_url(args, settings, parser)
    create_engine_with_schema(database_url)
    _logger.info("database_initialized", extra={"database_url": database_url})
    return 0


def cmd_sync_calendar(
    args: argparse.Namespace, *, settings: Settings, parser: argparse.ArgumentParser
) -> int:
    start_date = parse_iso_date(args.start_date)
    end_date = parse_iso_date(args.end_date)
    if start_date > end_date:
        parser.error("--start-date must be on or before --end-date")

    markets = args.markets or ["TWSE"]
    output_dir = args.output_dir or settings.output_dir
    database_url = args.database_url or settings.database_url
    engine = create_db_engine(database_url) if database_url else None
    if engine:
        create_schema(engine)

    official_trading_calendar = fetch_official_trading_calendar(
        start_date=start_date,
        end_date=end_date,
        markets=markets,
        settings=settings,
        source_mode=args.source_mode,
    )
    trading_calendar = build_trading_calendar(
        start_date=start_date,
        end_date=end_date,
        markets=markets,
        official_overrides=official_trading_calendar,
    )
    artifacts = save_trading_calendar(
        trading_calendar=trading_calendar,
        output_dir=output_dir,
        start_date=start_date,
        end_date=end_date,
    )
    persisted_counts = {}
    if engine:
        with Session(engine) as session:
            persisted_counts["trading_calendar"] = upsert_trading_calendar(
                session, trading_calendar
            )
            session.commit()

    _logger.info(
        "calendar_synced",
        extra={
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "markets": markets,
            "rows": int(len(trading_calendar.index)),
            "csv_path": str(artifacts["csv"]),
            "json_path": str(artifacts["json"]),
            "persisted_counts": persisted_counts,
        },
    )
    return 0


def cmd_sync_stocks(
    args: argparse.Namespace, *, settings: Settings, parser: argparse.ArgumentParser
) -> int:
    markets = args.markets or ["TWSE"]
    dataset_path = args.dataset_path or settings.stock_master_path
    diagnostics_path = (
        args.diagnostics_path or settings.output_dir / "stock_master" / "sync_diagnostics.json"
    )
    database_url = args.database_url or settings.database_url
    engine = create_db_engine(database_url) if database_url else None
    if engine:
        create_schema(engine)

    fetched_stock_master, diagnostics = fetch_stock_master_with_diagnostics(
        markets=markets,
        settings=settings,
        source_mode=args.source_mode,
    )
    existing_stock_master = load_stock_master(dataset_path)
    merged_stock_master = upsert_stock_master(existing_stock_master, fetched_stock_master)
    save_stock_master(merged_stock_master, dataset_path)
    save_stock_master_diagnostics(diagnostics, diagnostics_path)

    persisted_counts = {}
    if engine:
        with Session(engine) as session:
            persisted_counts["stocks"] = upsert_stock_master_rows(session, merged_stock_master)
            session.commit()

    _logger.info(
        "stocks_synced",
        extra={
            "markets": markets,
            "rows_fetched": int(len(fetched_stock_master.index)),
            "rows_in_dataset": int(len(merged_stock_master.index)),
            "dataset_path": str(dataset_path),
            "diagnostics_path": str(diagnostics_path),
            "diagnostic_failures": [
                diagnostic["market"]
                for diagnostic in diagnostics
                if diagnostic["final_status"] != "success"
            ],
            "persisted_counts": persisted_counts,
        },
    )
    return 0


def cmd_sync_institutional(
    args: argparse.Namespace, *, settings: Settings, parser: argparse.ArgumentParser
) -> int:
    trading_date = parse_iso_date(args.date)
    markets = args.markets or ["TWSE", "TPEX"]

    frames = []
    for market in markets:
        provider = build_institutional_provider(market)
        frames.append(
            provider.fetch_day(
                trading_date=trading_date,
                settings=settings,
                source_mode=args.source_mode,
            )
        )
    flows = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()

    if flows.empty:
        _logger.info(
            "institutional_sync_no_rows",
            extra={"trading_date": trading_date.isoformat(), "markets": markets},
        )
        print(f"無 {trading_date.isoformat()} 三大法人買賣超資料。")
        return 0

    database_url = require_database_url(args, settings, parser)
    engine = create_engine_with_schema(database_url)

    with Session(engine) as session:
        persisted_rows = upsert_institutional_flows(session, flows)
        session.commit()

    _logger.info(
        "institutional_synced",
        extra={
            "trading_date": trading_date.isoformat(),
            "markets": markets,
            "rows": persisted_rows,
        },
    )
    print(f"✅ 已同步 {trading_date.isoformat()} 三大法人買賣超，共 {persisted_rows} 筆。")
    return 0


def cmd_sync_main_force(
    args: argparse.Namespace, *, settings: Settings, parser: argparse.ArgumentParser
) -> int:
    start_date = parse_iso_date(args.start_date)
    end_date = parse_iso_date(args.end_date)
    if start_date > end_date:
        parser.error("--start-date must be on or before --end-date")

    database_url = require_database_url(args, settings, parser)
    engine = create_engine_with_schema(database_url)

    market = args.market
    if not market:
        with Session(engine) as session:
            for candidate in ("TWSE", "TPEX"):
                found = (
                    session.query(Stock)
                    .filter(Stock.market == candidate, Stock.symbol == args.symbol)
                    .first()
                )
                if found:
                    market = candidate
                    break
        if not market:
            market = "TWSE"
            print(
                f"⚠️ 股票主檔查無 {args.symbol}，市場以 TWSE 代入（可用 --market 指定）。",
                file=sys.stderr,
            )

    try:
        report = fetch_trading_daily_report(
            symbol=args.symbol,
            start_date=start_date,
            end_date=end_date,
            settings=settings,
        )
    except FinMindError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    main_force = compute_main_force_daily(report, top_n=args.top_n)
    if main_force.empty:
        print(f"無 {args.symbol} {start_date.isoformat()} ~ {end_date.isoformat()} 券商分點資料。")
        return 0

    with Session(engine) as session:
        persisted_rows = upsert_main_force_daily(
            session, market=market, symbol=args.symbol, frame=main_force, top_n=args.top_n
        )
        session.commit()

    _logger.info(
        "main_force_synced",
        extra={
            "symbol": args.symbol,
            "market": market,
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "top_n": args.top_n,
            "rows": persisted_rows,
        },
    )
    print(
        f"✅ 已同步 {market}:{args.symbol} 主力買賣超（Top {args.top_n}），共 {persisted_rows} 日。"
    )
    return 0
