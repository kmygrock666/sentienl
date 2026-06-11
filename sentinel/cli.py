from __future__ import annotations

import argparse
import sys
import uuid
from datetime import date
from pathlib import Path
from typing import List, Optional

import pandas as pd

from sentinel.backtest import run_backtest, save_backtest_results
from sentinel.calendar import build_trading_calendar, save_trading_calendar
from sentinel.completeness import build_run_completeness_summary
from sentinel.config import Settings
from sentinel.db import create_db_engine, create_schema
from sentinel.logging_utils import get_logger, setup_logging
from sentinel.official_calendar import fetch_official_trading_calendar
from sentinel.persistence import finish_job_run, persist_pipeline_results, start_job_run
from sentinel.pipeline import compute_indicators, fetch_prices, save_results, scan_strategy
from sentinel.quality import validate_daily_prices
from sentinel.query import (
    get_completeness,
    get_data_status,
    get_job_logs,
    get_latest_dates_by_market,
    get_quarantine_logs,
    get_scan_results,
)
from sentinel.stock_master import (
    fetch_stock_master_with_diagnostics,
    load_stock_master,
    save_stock_master,
    save_stock_master_diagnostics,
    upsert_stock_master,
)
from sentinel.storage import load_price_dataset, save_price_dataset, upsert_prices
from sentinel.strategies import load_strategy_definitions
from sentinel.utils import parse_iso_date

_logger = get_logger(__name__)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Taiwan stock strategy scanner")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser(
        "run", help="Fetch prices, compute indicators, and scan strategy"
    )
    run_parser.add_argument(
        "--start-date", required=True, help="Inclusive start date in YYYY-MM-DD"
    )
    run_parser.add_argument("--end-date", required=True, help="Inclusive end date in YYYY-MM-DD")
    run_parser.add_argument(
        "--trading-date",
        help="Trading date to scan in YYYY-MM-DD. Defaults to --end-date.",
    )
    run_parser.add_argument(
        "--market",
        action="append",
        dest="markets",
        default=[],
        help="Market to fetch. Currently supports TWSE. Repeatable.",
    )
    run_parser.add_argument(
        "--dataset-path",
        type=Path,
        help="Override the canonical daily price dataset path.",
    )
    run_parser.add_argument(
        "--output-dir",
        type=Path,
        help="Override the output directory for scan artifacts.",
    )
    run_parser.add_argument(
        "--data-version",
        help="Override the data version written to outputs.",
    )
    run_parser.add_argument(
        "--database-url",
        help="SQLAlchemy database URL. Defaults to TS_DATABASE_URL from environment.",
    )
    run_parser.add_argument(
        "--calendar-source-mode",
        choices=["auto", "fixture", "network"],
        default="auto",
        help="Trading calendar source mode.",
    )
    run_parser.add_argument(
        "--price-source-mode",
        choices=["auto", "fixture", "network"],
        default="auto",
        help="Daily price source mode.",
    )
    run_parser.add_argument(
        "--strategy-path",
        type=Path,
        help="Strategy config path. Defaults to config/strategies.json if present, otherwise built-in defaults.",
    )
    run_parser.add_argument(
        "--skip-indicators",
        action="store_true",
        help="Skip technical indicator computation (MA, RSI, etc.).",
    )
    run_parser.add_argument(
        "--skip-strategies",
        action="store_true",
        help="Skip strategy loading and scanning.",
    )
    run_parser.add_argument(
        "--direction",
        choices=["long", "short"],
        help="Filter strategies by direction (long or short).",
    )

    sync_parser = subparsers.add_parser(
        "sync", help="Automatically fetch missing prices until today"
    )
    sync_parser.add_argument(
        "--market",
        action="append",
        dest="markets",
        default=[],
        help="Market to sync. Repeatable. Defaults to TWSE, TPEX.",
    )
    sync_parser.add_argument(
        "--database-url",
        help="SQLAlchemy database URL. Defaults to TS_DATABASE_URL.",
    )
    sync_parser.add_argument(
        "--scan",
        action="store_true",
        help="Execute strategy scan for the latest date after sync.",
    )
    sync_parser.add_argument(
        "--direction",
        choices=["long", "short"],
        help="Filter scan results by direction (long or short). Only meaningful with --scan.",
    )

    init_db_parser = subparsers.add_parser("init-db", help="Initialize database schema")
    init_db_parser.add_argument(
        "--database-url",
        help="SQLAlchemy database URL. Defaults to TS_DATABASE_URL from environment.",
    )

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

    backtest_parser = subparsers.add_parser(
        "backtest", help="Run backtest using the local price dataset"
    )
    backtest_parser.add_argument(
        "--start-date", required=True, help="Inclusive start date in YYYY-MM-DD"
    )
    backtest_parser.add_argument(
        "--end-date", required=True, help="Inclusive end date in YYYY-MM-DD"
    )
    backtest_parser.add_argument(
        "--market",
        action="append",
        dest="markets",
        default=[],
        help="Market to include. Repeatable.",
    )
    backtest_parser.add_argument(
        "--dataset-path",
        type=Path,
        help="Override the canonical daily price dataset path.",
    )
    backtest_parser.add_argument(
        "--output-dir",
        type=Path,
        help="Override the output directory for backtest artifacts.",
    )
    backtest_parser.add_argument(
        "--database-url",
        help="SQLAlchemy database URL. Defaults to TS_DATABASE_URL from environment.",
    )
    backtest_parser.add_argument(
        "--strategy-path",
        type=Path,
        help="Strategy config path. Defaults to config/strategies.json if present, otherwise built-in defaults.",
    )
    backtest_parser.add_argument(
        "--benchmark-symbol",
        help="Optional benchmark symbol for total return comparison.",
    )
    backtest_parser.add_argument(
        "--execution-model",
        choices=["daily", "minute_bar"],
        default="daily",
        help="Execution model: 'daily' (next_open_to_close) or 'minute_bar' (5m bar precise entry/exit). Default: daily.",
    )
    backtest_parser.add_argument(
        "--strategy-mode",
        choices=["standard", "tomorrow_star"],
        default="standard",
        help="Strategy scan mode. 'standard' uses config/strategies.json. 'tomorrow_star' generates intraday historical signals.",
    )
    backtest_parser.add_argument(
        "--intraday-database-url",
        help="SQLAlchemy intraday database URL. Defaults to TS_INTRADAY_DATABASE_URL from environment.",
    )
    backtest_parser.add_argument(
        "--symbol",
        help="Filter backtest to a specific stock symbol.",
    )
    backtest_parser.add_argument(
        "--initial-capital",
        type=float,
        help="Total budget per strategy for capital-constrained backtesting.",
    )
    backtest_parser.add_argument(
        "--position-size",
        type=float,
        default=100000,
        help="Fixed budget per single trade. Default: 100,000.",
    )

    update_intraday_parser = subparsers.add_parser(
        "update-intraday-stats", help="Update historical win rate stats for intraday strategies"
    )
    update_intraday_parser.add_argument(
        "--database-url",
        help="SQLAlchemy database URL. Defaults to TS_DATABASE_URL from environment.",
    )
    update_intraday_parser.add_argument(
        "--lookback-days",
        type=int,
        default=180,
        help="Lookback period in days for win rate calculation.",
    )
    update_intraday_parser.add_argument(
        "--gain-threshold",
        type=float,
        default=0.05,
        help="Daily gain threshold (0.05 targets 5%+ gains).",
    )
    update_intraday_parser.add_argument(
        "--min-samples",
        type=int,
        default=5,
        help="Minimum number of samples required to calculate win rate.",
    )

    capture_snapshot_parser = subparsers.add_parser(
        "capture-intraday-snapshot", help="Capture current price and volume snapshot from MIS"
    )
    capture_snapshot_parser.add_argument(
        "--database-url",
        help="SQLAlchemy database URL. Defaults to TS_DATABASE_URL from environment.",
    )
    capture_snapshot_parser.add_argument(
        "--time",
        default="12:00",
        help="Label for this snapshot (e.g., 12:00).",
    )
    capture_snapshot_parser.add_argument(
        "--top",
        type=int,
        default=300,
        help="Number of top stocks by volume to capture.",
    )

    intraday_run_parser = subparsers.add_parser(
        "run-intraday", help="Run Tomorrow's Star strategy scan at 13:00"
    )
    intraday_run_parser.add_argument(
        "--database-url",
        help="SQLAlchemy database URL. Defaults to TS_DATABASE_URL from environment.",
    )
    intraday_run_parser.add_argument(
        "--top",
        type=int,
        default=300,
        help="Number of top stocks by volume to monitor.",
    )
    intraday_run_parser.add_argument(
        "--min-gain",
        type=float,
        default=0.075,
        help="Daily gain threshold (default: 0.075 for 7.5%+).",
    )
    intraday_run_parser.add_argument(
        "--notify-telegram",
        action="store_true",
        help="Send results to Telegram Channel.",
    )

    update_trades_parser = subparsers.add_parser(
        "update-intraday-trades", help="Close yesterday's open intraday trades using today's prices"
    )
    update_trades_parser.add_argument(
        "--database-url",
        help="SQLAlchemy database URL. Defaults to TS_DATABASE_URL from environment.",
    )
    update_trades_parser.add_argument(
        "--real-time",
        action="store_true",
        help="Fetch real-time opening prices from MIS instead of relying on DailyPrice table.",
    )
    update_trades_parser.add_argument(
        "--price-type",
        choices=["open", "last"],
        default="open",
        help="Price type to use for closing: 'open' (opening price) or 'last' (current market price). Default is 'open'.",
    )
    update_trades_parser.add_argument(
        "--allow-today",
        action="store_true",
        help="Allow closing trades opened today (useful for testing).",
    )

    monitor_trades_parser = subparsers.add_parser(
        "monitor-intraday-trades", help="Monitor open trades for 2% SL/TP thresholds"
    )
    monitor_trades_parser.add_argument(
        "--threshold",
        type=float,
        default=0.02,
        help="SL/TP threshold (default: 0.02 for 2%%)",
    )
    monitor_trades_parser.add_argument(
        "--force-close",
        action="store_true",
        help="Force close all open trades.",
    )
    monitor_trades_parser.add_argument(
        "--allow-today",
        action="store_true",
        help="Allow monitoring/closing trades opened today.",
    )
    monitor_trades_parser.add_argument(
        "--database-url",
        help="SQLAlchemy database URL. Defaults to TS_DATABASE_URL from environment.",
    )

    add_trade_parser = subparsers.add_parser(
        "add-intraday-trade", help="Manually add a simulated intraday trade"
    )
    add_trade_parser.add_argument(
        "--market", default=None, help="Market (TWSE or TPEX). Auto-detected if omitted."
    )
    add_trade_parser.add_argument("--symbol", required=True, help="Stock symbol")
    add_trade_parser.add_argument("--price", type=float, required=True, help="Entry price")
    add_trade_parser.add_argument("--notes", help="Optional notes for the trade")
    add_trade_parser.add_argument(
        "--database-url",
        help="SQLAlchemy database URL. Defaults to TS_DATABASE_URL from environment.",
    )

    import_bars_parser = subparsers.add_parser(
        "import-minute-bars", help="Import 1m CSV bars into DB as aggregated 5m bars"
    )
    import_bars_parser.add_argument(
        "--csv",
        type=Path,
        required=True,
        help="Path to FinMind 1m CSV file.",
    )
    import_bars_parser.add_argument(
        "--chunk-size",
        type=int,
        default=100_000,
        help="Rows per chunk for processing. Default 100,000.",
    )
    import_bars_parser.add_argument(
        "--database-url",
        help="SQLAlchemy main database URL (for stock-market mapping). Defaults to TS_DATABASE_URL.",
    )
    import_bars_parser.add_argument(
        "--intraday-database-url",
        help="SQLAlchemy intraday database URL. Defaults to TS_INTRADAY_DATABASE_URL.",
    )

    scheduler_parser = subparsers.add_parser(
        "scheduler", help="Start the automated intraday strategy scheduler"
    )
    scheduler_parser.add_argument(
        "--database-url",
        help="SQLAlchemy database URL. Defaults to TS_DATABASE_URL from environment.",
    )

    inspect_parser = subparsers.add_parser("inspect", help="Inspect database state and results")

    clear_trades_parser = subparsers.add_parser(
        "clear-intraday-trades", help="Clear all simulated intraday trade records"
    )
    clear_trades_parser.add_argument(
        "--database-url",
        help="SQLAlchemy database URL. Defaults to TS_DATABASE_URL from environment.",
    )

    inspect_subparsers = inspect_parser.add_subparsers(dest="inspect_command", required=True)

    inspect_subparsers.add_parser("status", help="Show latest capture dates for all tables")

    completeness_parser = inspect_subparsers.add_parser(
        "completeness", help="Check data completeness for a date"
    )
    completeness_parser.add_argument("--date", required=True, help="Target date in YYYY-MM-DD")

    results_parser = inspect_subparsers.add_parser("results", help="Show strategy scan results")
    results_parser.add_argument("--strategy", help="Filter by strategy ID")
    results_parser.add_argument("--date", help="Target date in YYYY-MM-DD")
    results_parser.add_argument("--min-volume", type=int, help="Filter by minimum volume")
    results_parser.add_argument(
        "--direction", choices=["long", "short"], help="Filter by strategy direction"
    )
    results_parser.add_argument(
        "--limit", type=int, default=50, help="Maximum number of results (default: 50)"
    )

    logs_parser = inspect_subparsers.add_parser("logs", help="Show job or quarantine logs")
    logs_parser.add_argument(
        "--type", choices=["jobs", "quarantine"], default="jobs", help="Log type to show"
    )
    logs_parser.add_argument(
        "--limit", type=int, default=20, help="Maximum number of entries (default: 20)"
    )

    inspect_intraday_parser = inspect_subparsers.add_parser(
        "intraday-trades", help="Show simulated intraday trade logs"
    )
    inspect_intraday_parser.add_argument(
        "--export",
        action="store_true",
        help="Export the trade logs to a CSV file in outputs/reports/.",
    )

    for p in [
        inspect_parser,
        status_parser := inspect_subparsers.choices.get("status"),
        completeness_parser,
        results_parser,
        logs_parser,
        inspect_subparsers.choices.get("intraday-trades"),
    ]:
        if p:
            p.add_argument("--database-url", help="SQLAlchemy database URL")

    check_parser = subparsers.add_parser(
        "check-stock",
        help="Check which observation signals are triggered for a specific stock on a given date",
    )
    check_parser.add_argument("--symbol", required=True, help="Stock symbol to inspect (e.g. 2492)")
    check_parser.add_argument(
        "--date",
        help="Trading date in YYYY-MM-DD. Defaults to the latest available date for the stock.",
    )
    check_parser.add_argument(
        "--dataset-path", type=Path, help="Override the canonical daily price dataset path."
    )
    check_parser.add_argument(
        "--signal-path", type=Path, help="Signal config path. Defaults to config/signals.json."
    )
    check_parser.add_argument(
        "--database-url", help="SQLAlchemy database URL. Defaults to TS_DATABASE_URL."
    )

    backfill_agg_parser = subparsers.add_parser(
        "backfill-aggregated-bars",
        help="One-time backfill of daily_prices_3d and daily_prices_47d from existing price data",
    )
    backfill_agg_parser.add_argument(
        "--database-url", help="SQLAlchemy database URL. Defaults to TS_DATABASE_URL."
    )
    backfill_agg_parser.add_argument(
        "--dataset-path", type=Path, help="Override the canonical daily price dataset path."
    )

    yahoo_parser = subparsers.add_parser(
        "backfill-yahoo",
        help="Backfill missing historical prices from Yahoo Finance",
    )
    yahoo_parser.add_argument(
        "--start-date", required=True, help="Inclusive start date in YYYY-MM-DD"
    )
    yahoo_parser.add_argument("--end-date", required=True, help="Inclusive end date in YYYY-MM-DD")
    yahoo_parser.add_argument(
        "--market",
        action="append",
        dest="markets",
        default=[],
        help="Market to backfill (TWSE or TPEX). Repeatable. Defaults to TWSE, TPEX.",
    )
    yahoo_parser.add_argument(
        "--database-url", help="SQLAlchemy database URL. Defaults to TS_DATABASE_URL."
    )

    return parser


def _apply_institutional_enrichment(frame: pd.DataFrame, engine) -> pd.DataFrame:
    """以資料庫中的法人買賣超 enrich 指標 frame；失敗時記 warning 並回傳原 frame。"""
    try:
        from sqlalchemy.orm import Session as _SASession

        from sentinel.institutional import enrich_with_institutional, load_institutional_frame

        _date_col: pd.Series = frame["trading_date"]  # type: ignore[assignment]
        _dates = pd.DatetimeIndex(pd.to_datetime(_date_col)).date  # ndarray[date]
        with _SASession(engine) as session:
            flows = load_institutional_frame(session, start_date=min(_dates), end_date=max(_dates))
        enriched = enrich_with_institutional(frame, flows)
        _logger.info("institutional_enriched", extra={"flow_rows": len(flows.index)})
        return enriched
    except Exception as exc:  # noqa: BLE001 - enrichment 失敗不應中斷主流程
        _logger.warning("institutional_enrich_failed", extra={"error": str(exc)})
        return frame


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    settings = Settings()
    setup_logging(settings.log_level)
    logger = get_logger(__name__)

    if args.command == "init-db":
        database_url = args.database_url or settings.database_url
        if not database_url:
            parser.error("--database-url is required or set TS_DATABASE_URL in the environment")

        engine = create_db_engine(database_url)
        create_schema(engine)
        logger.info("database_initialized", extra={"database_url": database_url})
        return 0

    if args.command == "sync-calendar":
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
            from sqlalchemy.orm import Session

            from sentinel.persistence import upsert_trading_calendar

            with Session(engine) as session:
                persisted_counts["trading_calendar"] = upsert_trading_calendar(
                    session, trading_calendar
                )
                session.commit()

        logger.info(
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

    if args.command == "sync-stocks":
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
            from sqlalchemy.orm import Session

            from sentinel.persistence import upsert_stock_master_rows

            with Session(engine) as session:
                persisted_counts["stocks"] = upsert_stock_master_rows(session, merged_stock_master)
                session.commit()

        logger.info(
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

    if args.command == "sync-institutional":
        trading_date = parse_iso_date(args.date)
        markets = args.markets or ["TWSE", "TPEX"]

        from sentinel.institutional import build_institutional_provider

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
            logger.info(
                "institutional_sync_no_rows",
                extra={"trading_date": trading_date.isoformat(), "markets": markets},
            )
            print(f"無 {trading_date.isoformat()} 三大法人買賣超資料。")
            return 0

        database_url = args.database_url or settings.database_url
        if not database_url:
            parser.error("--database-url is required or set TS_DATABASE_URL in the environment")

        engine = create_db_engine(database_url)
        create_schema(engine)

        from sqlalchemy.orm import Session

        from sentinel.persistence import upsert_institutional_flows

        with Session(engine) as session:
            persisted_rows = upsert_institutional_flows(session, flows)
            session.commit()

        logger.info(
            "institutional_synced",
            extra={
                "trading_date": trading_date.isoformat(),
                "markets": markets,
                "rows": persisted_rows,
            },
        )
        print(f"✅ 已同步 {trading_date.isoformat()} 三大法人買賣超，共 {persisted_rows} 筆。")
        return 0

    if args.command == "sync-main-force":
        start_date = parse_iso_date(args.start_date)
        end_date = parse_iso_date(args.end_date)
        if start_date > end_date:
            parser.error("--start-date must be on or before --end-date")

        database_url = args.database_url or settings.database_url
        if not database_url:
            parser.error("--database-url is required or set TS_DATABASE_URL in the environment")

        from sqlalchemy.orm import Session

        from sentinel.main_force import (
            FinMindError,
            compute_main_force_daily,
            fetch_trading_daily_report,
        )
        from sentinel.persistence import upsert_main_force_daily

        engine = create_db_engine(database_url)
        create_schema(engine)

        market = args.market
        if not market:
            from sentinel.models import Stock

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
            print(
                f"無 {args.symbol} {start_date.isoformat()} ~ {end_date.isoformat()} 券商分點資料。"
            )
            return 0

        with Session(engine) as session:
            persisted_rows = upsert_main_force_daily(
                session, market=market, symbol=args.symbol, frame=main_force, top_n=args.top_n
            )
            session.commit()

        logger.info(
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

    if args.command == "import-minute-bars":
        intraday_url = args.intraday_database_url or settings.intraday_database_url
        if not intraday_url:
            parser.error("--intraday-database-url is required or set TS_INTRADAY_DATABASE_URL")

        csv_path = args.csv
        if not csv_path.exists():
            parser.error(f"CSV file not found: {csv_path}")

        from sqlalchemy.orm import Session

        from sentinel.minute_bars import import_minute_bars_csv

        intraday_engine = create_db_engine(intraday_url)
        create_schema(intraday_engine)

        # 獲取主表中的代號-市場映射，以修正 CSV 中不可靠的 exchange 標籤
        database_url = args.database_url or settings.database_url
        symbol_market_map = {}
        if database_url:
            from sentinel.models import Stock

            main_engine = create_db_engine(database_url)
            with Session(main_engine) as main_session:
                stocks = main_session.query(Stock.symbol, Stock.market).all()
                symbol_market_map = {s.symbol: s.market for s in stocks}

        with Session(intraday_engine) as intraday_session:
            print(f"匯入分鐘 K 線: {csv_path}")
            print(f"寫入至資料庫: {intraday_url}")
            print(f"Chunk size: {args.chunk_size}")
            if symbol_market_map:
                print(f"啟動標的主檔校正：已載入 {len(symbol_market_map)} 筆代號映射")
            print("匯入中（1m → 5m 聚合）... 本次採用極速 bulk insert 優化！")
            total = import_minute_bars_csv(
                intraday_session,
                csv_path,
                chunk_size=args.chunk_size,
                symbol_market_map=symbol_market_map,
            )
            print(f"\n✅ 匯入完成，共寫入 {total:,} 筆 5m K 線。")
        return 0

    if args.command == "backtest":
        start_date = parse_iso_date(args.start_date)
        end_date = parse_iso_date(args.end_date)
        if start_date > end_date:
            parser.error("--start-date must be on or before --end-date")

        dataset_path = args.dataset_path or settings.price_dataset_path
        output_dir = args.output_dir or settings.output_dir
        database_url = args.database_url or settings.database_url
        intraday_url = args.intraday_database_url or settings.intraday_database_url

        engine = create_db_engine(database_url) if database_url else None
        intraday_engine = create_db_engine(intraday_url) if intraday_url else None

        if engine:
            create_schema(engine)
        if intraday_engine:
            create_schema(intraday_engine)

        strategy_definitions = load_strategy_definitions(
            args.strategy_path or settings.strategy_config_path
        )
        backtest_run_id = uuid.uuid4().hex

        if engine:
            start_job_run(engine=engine, run_id=backtest_run_id, job_name="backtest")

        try:
            prices = load_price_dataset(dataset_path)
            markets = (
                args.markets or sorted(prices["market"].dropna().unique().tolist())
                if not prices.empty
                else ["TWSE"]
            )
            if not prices.empty:
                prices = prices[prices["market"].isin(markets)].copy()
            enriched_prices = compute_indicators(prices)

            # Apply symbol filter if provided
            if getattr(args, "symbol", None):
                enriched_prices = enriched_prices[enriched_prices["symbol"] == args.symbol].copy()
                if enriched_prices.empty:
                    print(f"⚠️ No data found for symbol: {args.symbol} in the dataset.")
                    return 0
                print(
                    f"📊 Filtering backtest to symbol: {args.symbol} ({len(enriched_prices)} rows)"
                )

            # 依據 execution model 選擇引擎
            use_minute_bar = getattr(args, "execution_model", "daily") == "minute_bar"

            if use_minute_bar:
                if not database_url or not intraday_url:
                    parser.error(
                        "minute_bar execution model requires both --database-url and --intraday-database-url (or TS_DATABASE_URL and TS_INTRADAY_DATABASE_URL)"
                    )
                from sqlalchemy.orm import Session as SASession

                from sentinel.backtest_minute import (
                    run_minute_backtest,
                    save_minute_backtest_results,
                )

                with (
                    SASession(engine) as bt_session,
                    SASession(intraday_engine) as intraday_session,
                ):
                    reports, trades = run_minute_backtest(
                        prices_with_indicators=enriched_prices,
                        strategies=strategy_definitions,
                        start_date=start_date,
                        end_date=end_date,
                        daily_session=bt_session,
                        intraday_session=intraday_session,
                        benchmark_symbol=args.benchmark_symbol,
                        strategy_mode=getattr(args, "strategy_mode", "standard"),
                        initial_capital=getattr(args, "initial_capital", None),
                        position_size=getattr(args, "position_size", 100000),
                    )
                artifacts = save_minute_backtest_results(
                    reports=reports,
                    trades=trades,
                    output_dir=output_dir,
                    start_date=start_date,
                    end_date=end_date,
                    initial_capital=getattr(args, "initial_capital", None),
                )
            else:
                reports, trades = run_backtest(
                    prices_with_indicators=enriched_prices,
                    strategies=strategy_definitions,
                    start_date=start_date,
                    end_date=end_date,
                    benchmark_symbol=args.benchmark_symbol,
                    initial_capital=getattr(args, "initial_capital", None),
                    position_size=getattr(args, "position_size", 100000),
                )
                artifacts = save_backtest_results(
                    reports=reports,
                    trades=trades,
                    output_dir=output_dir,
                    start_date=start_date,
                    end_date=end_date,
                    initial_capital=getattr(args, "initial_capital", None),
                )

            if engine:
                finish_job_run(
                    engine=engine,
                    run_id=backtest_run_id,
                    status="success",
                    rows_in=int(len(prices.index)),
                    rows_out=int(len(trades.index)),
                )

            logger.info(
                "backtest_finished",
                extra={
                    "run_id": backtest_run_id,
                    "markets": markets,
                    "strategies": [
                        strategy["strategy_id"]
                        for strategy in strategy_definitions
                        if strategy.get("is_active", True)
                    ],
                    "trades": int(len(trades.index)),
                    "report_rows": int(len(reports.index)),
                    "report_path": str(artifacts["report"]),
                    "trades_path": str(artifacts["trades"]),
                    "report_md": str(artifacts["report_md"]),
                    "trades_md": str(artifacts["trades_md"]),
                },
            )

            print("\n" + "=" * 60)
            print("📊 回測執行完畢 - 交易結果統計")
            print("=" * 60)
            print(f"📄 績效報告 (MD): {artifacts['report_md']}")
            print(f"📄 交易明細 (MD): {artifacts['trades_md']}")
            pd.set_option("display.unicode.east_asian_width", True)
            if not reports.empty:
                print("\n📈 策略總結:")
                disp_reports = reports[
                    [
                        "strategy_name",
                        "trades",
                        "win_rate",
                        "avg_trade_return",
                        "total_return",
                        "cagr",
                        "mdd",
                    ]
                ].copy()
                disp_reports.columns = [
                    "策略名稱",
                    "交易次數",
                    "勝率",
                    "平均報酬",
                    "總報酬率",
                    "年化報酬",
                    "最大回撤",
                ]
                for col in ["勝率", "平均報酬", "總報酬率", "年化報酬", "最大回撤"]:
                    disp_reports[col] = disp_reports[col].apply(lambda x: f"{x:.2%}")
                print(disp_reports.to_string(index=False))
            else:
                print("\n📈 策略總結: 無交易紀錄")

            if not trades.empty:
                print("\n📋 交易明細 (前 20 筆):")
                disp_trades = trades.head(20).copy()

                stock_master = load_stock_master(settings.stock_master_path)
                if not stock_master.empty:
                    disp_trades["symbol"] = disp_trades["symbol"].astype(str)
                    stock_master["symbol"] = stock_master["symbol"].astype(str)
                    disp_trades = pd.merge(
                        disp_trades,
                        stock_master[["market", "symbol", "name", "industry"]],
                        on=["market", "symbol"],
                        how="left",
                    )
                else:
                    disp_trades["name"] = ""
                    disp_trades["industry"] = ""

                market_map = {"TWSE": "上市", "TPEX": "上櫃"}
                disp_trades["market"] = disp_trades["market"].map(lambda x: market_map.get(x, x))

                disp_columns = [
                    "strategy_name",
                    "market",
                    "symbol",
                    "name",
                    "industry",
                    "entry_date",
                    "entry_price",
                    "exit_date",
                    "exit_price",
                    "trade_return",
                ]
                # ensure they exist (fallback if merge failed)
                for col in disp_columns:
                    if col not in disp_trades.columns:
                        disp_trades[col] = ""

                disp_trades = disp_trades[disp_columns]
                disp_trades.columns = [
                    "策略名稱",
                    "市場",
                    "代號",
                    "名稱",
                    "產業",
                    "進場日",
                    "進場價",
                    "出場日",
                    "出場價",
                    "報酬率",
                ]

                # Format float return
                disp_trades["報酬率"] = pd.to_numeric(disp_trades["報酬率"], errors="coerce").apply(
                    lambda x: f"{x:.2%}" if pd.notna(x) else ""
                )

                print(disp_trades.to_string(index=False))
                if len(trades.index) > 20:
                    print(f"... 還有 {len(trades.index) - 20} 筆紀錄，請查看輸出檔案。")
            else:
                print("\n📋 交易明細: 無")
            print("=" * 60 + "\n")

            return 0
        except Exception as exc:
            if engine:
                finish_job_run(
                    engine=engine,
                    run_id=backtest_run_id,
                    status="failed",
                    error_summary=str(exc)[:1000],
                )
            logger.error("backtest_failed", extra={"run_id": backtest_run_id, "error": str(exc)})
            raise

    if args.command == "update-intraday-stats":
        database_url = args.database_url or settings.database_url
        if not database_url:
            parser.error("--database-url is required or set TS_DATABASE_URL in the environment")

        from sqlalchemy.orm import Session

        from sentinel.intraday.indicators import calculate_intraday_win_rates

        engine = create_db_engine(database_url)
        create_schema(engine)  # Ensure new tables exist

        with Session(engine) as session:
            print(
                f"Updating intraday win rates (Lookback: {args.lookback_days} days, Threshold: {args.gain_threshold*100}%)..."
            )
            count = calculate_intraday_win_rates(
                session=session,
                lookback_days=args.lookback_days,
                gain_threshold=args.gain_threshold,
                min_samples=args.min_samples,
            )
            print(f"Successfully updated win rates for {count} stocks.")
            return 0

    if args.command == "capture-intraday-snapshot":
        database_url = args.database_url or settings.database_url
        if not database_url:
            parser.error("--database-url is required or set TS_DATABASE_URL in the environment")

        from sqlalchemy.orm import Session

        from sentinel.intraday.snapshots import capture_intraday_snapshot

        engine = create_db_engine(database_url)
        create_schema(engine)

        with Session(engine) as session:
            print(f"Capturing intraday snapshot at {args.time} for top {args.top} stocks...")
            count = capture_intraday_snapshot(session, args.time, top_n=args.top)
            print(f"Successfully captured {count} snapshots.")
            return 0

    if args.command == "run-intraday":
        database_url = args.database_url or settings.database_url
        if not database_url:
            parser.error("--database-url is required or set TS_DATABASE_URL in the environment")

        from sqlalchemy.orm import Session

        from sentinel.intraday.engine import run_tomorrow_star_scan

        engine = create_db_engine(database_url)
        create_schema(engine)

        with Session(engine) as session:
            print(f"Running Tomorrow's Star Scan (Top {args.top}, Gain > {args.min_gain*100}%)...")
            results = run_tomorrow_star_scan(session, top_n=args.top, min_gain=args.min_gain)

            if not results:
                print("No stocks matched the strategy criteria today.")
            else:
                print("\n" + "=" * 80)
                print(f"🌟 明日之星 - 13:00 策略掃描結果 ({len(results)} 筆)")
                print("=" * 80)

                df = pd.DataFrame(results)
                # Reorder and rename for display
                df = df[
                    [
                        "market",
                        "symbol",
                        "name",
                        "close",
                        "gain",
                        "vol_ratio",
                        "vol_surge_ratio",
                        "win_rate",
                        "is_great_power",
                        "is_limit_up",
                    ]
                ]
                market_map = {"TWSE": "上市", "TPEX": "上櫃"}
                df["market"] = df["market"].map(lambda x: market_map.get(x, x))
                df.columns = [
                    "市場",
                    "代號",
                    "名稱",
                    "現價",
                    "漲幅",
                    "量能比",
                    "午盤比",
                    "歷史勝率",
                    "大戶單",
                    "漲停",
                ]

                df["漲幅"] = df["漲幅"].apply(lambda x: f"{x:.2%}")
                df["量能比"] = df["量能比"].apply(lambda x: f"{x:.2f}x")
                df["午盤比"] = df["午盤比"].apply(lambda x: f"{x:.2f}x")
                df["歷史勝率"] = df["歷史勝率"].apply(lambda x: f"{x:.0%}")
                df["大戶單"] = df["大戶單"].apply(lambda x: "✅" if x else " ")
                df["漲停"] = df["漲停"].apply(lambda x: "🚩" if x else " ")

                pd.set_option("display.unicode.east_asian_width", True)
                print(df.to_string(index=False))
                print("=" * 80 + "\n")

                if args.notify_telegram:
                    from sentinel.intraday.notifiers import build_telegram_notifier

                    notifier = build_telegram_notifier(settings)
                    if notifier is not None:
                        print("Sending notifications to Telegram...")
                        notifier.send_scan_results(results)
                    else:
                        print(
                            "Telegram credentials not configured "
                            "(TS_TG_TOKEN / TS_TG_CHAT_ID); skipping notification.",
                            file=sys.stderr,
                        )
            return 0

    if args.command == "update-intraday-trades":
        database_url = args.database_url or settings.database_url
        if not database_url:
            parser.error("--database-url is required or set TS_DATABASE_URL in the environment")

        from sqlalchemy.orm import Session

        from sentinel.intraday.trades import update_intraday_trades

        engine = create_db_engine(database_url)
        create_schema(engine)

        with Session(engine) as session:
            print(
                f"Closing open trades (Real-time: {args.real_time}, Type: {args.price_type}, Allow Today: {args.allow_today})..."
            )
            count = update_intraday_trades(
                session,
                real_time=args.real_time,
                price_type=args.price_type,
                allow_today=args.allow_today,
            )
            print(f"Successfully closed {count} trades.")
            return 0

    elif args.command == "monitor-intraday-trades":
        database_url = args.database_url or settings.database_url
        if not database_url:
            parser.error("--database-url is required or set TS_DATABASE_URL in the environment")

        from sqlalchemy.orm import Session

        from sentinel.intraday.trades import monitor_and_close_intraday_trades

        engine = create_db_engine(database_url)

        with Session(engine) as session:
            print(
                f"Monitoring SL/TP triggers (Threshold: {args.threshold}, Force Close: {args.force_close}, Allow Today: {args.allow_today})..."
            )
            count = monitor_and_close_intraday_trades(
                session,
                threshold=args.threshold,
                force_close=args.force_close,
                allow_today=args.allow_today,
            )
            print(f"Executed monitor: {count} trades closed.")
            return 0

    elif args.command == "add-intraday-trade":
        database_url = args.database_url or settings.database_url
        if not database_url:
            parser.error("--database-url is required or set TS_DATABASE_URL in the environment")

        from sqlalchemy.orm import Session

        from sentinel.intraday.trades import add_manual_intraday_trade

        engine = create_db_engine(database_url)

        with Session(engine) as session:
            success = add_manual_intraday_trade(
                session=session,
                market=args.market,
                symbol=args.symbol,
                entry_price=args.price,
                notes=args.notes,
            )
            if success:
                # Re-query to get the actual market (may have been auto-detected)
                market_label = args.market or "auto-detected"
                print(f"Successfully added trade for {market_label}:{args.symbol} at {args.price}")
            else:
                print(f"Failed to add trade for {args.symbol}")
            return 0

    elif args.command == "clear-intraday-trades":
        database_url = args.database_url or settings.database_url
        if not database_url:
            parser.error("--database-url is required or set TS_DATABASE_URL in the environment")

        from sqlalchemy.orm import Session

        from sentinel.intraday.trades import clear_intraday_trades

        engine = create_db_engine(database_url)

        with Session(engine) as session:
            count = clear_intraday_trades(session)
            print(f"Successfully cleared {count} intraday trade records.")
            return 0

    if args.command == "scheduler":
        database_url = args.database_url or settings.database_url
        if not database_url:
            parser.error("--database-url is required or set TS_DATABASE_URL in the environment")

        from sentinel.intraday.scheduler import IntradayScheduler

        scheduler = IntradayScheduler(database_url)
        scheduler.start()
        return 0

    if args.command == "inspect":
        database_url = args.database_url or settings.database_url
        if not database_url:
            parser.error("--database-url is required or set TS_DATABASE_URL in the environment")

        from sqlalchemy.orm import Session

        engine = create_db_engine(database_url)

        with Session(engine) as session:
            if args.inspect_command == "status":
                data = get_data_status(session)

                descriptions = {
                    "daily_prices": "日成交價",
                    "technical_indicators": "技術指標",
                    "scan_results": "策略掃描結果",
                    "trading_calendar": "交易日曆",
                    "institutional_flows": "三大法人買賣超",
                    "margin_balances": "融資融券餘額",
                    "intraday_snapshots": "日內量能快照",
                    "intraday_trades": "日內模擬交易紀錄",
                }

                print("\n" + "=" * 90)
                print(
                    f"{'資料表 (Table Name)':<35} | {'最舊 (Min)':<12} | {'最新 (Max)':<12} | {'總筆數 (Records)':>13}"
                )
                print("-" * 90)
                for table_name, status in data.items():
                    desc = descriptions.get(table_name, "")
                    label = f"{table_name} ({desc})" if desc else table_name
                    print(
                        f"{label:<35} | {status['earliest']:<12} | {status['latest']:<12} | {status['count']:>13,}"
                    )
                print("=" * 90 + "\n")

            elif args.inspect_command == "completeness":
                target_date = parse_iso_date(args.date)
                data = get_completeness(session, target_date)
                # Simplified output for terminal
                print(f"Date: {data['date']}")
                print(f"Ratio: {data['ratio']:.2%} ({data['actual']}/{data['expected']})")
                if data["missing"]:
                    print("\nMissing Stocks:")
                    for m in data["missing"]:
                        print(f"  - {m['market']}:{m['symbol']}")

            elif args.inspect_command == "results":
                target_date = parse_iso_date(args.date) if args.date else None
                data = get_scan_results(
                    session,
                    strategy_id=args.strategy,
                    target_date=target_date,
                    min_volume=args.min_volume,
                    limit=args.limit,
                )
                if not data:
                    print("No results found.")
                else:
                    pd.set_option("display.unicode.east_asian_width", True)
                    df = pd.DataFrame(data)

                    strategy_defs = load_strategy_definitions(settings.strategy_config_path)
                    strategy_dir_map = {
                        s["strategy_id"]: s.get("params_json", {}).get("direction", "long")
                        for s in strategy_defs
                    }
                    df["direction"] = df["strategy"].map(strategy_dir_map).fillna("long")

                    if args.direction:
                        df = df[df["direction"] == args.direction].copy()

                    if df.empty:
                        print(f"No results found for direction: {args.direction}")
                        return 0

                    stock_master = load_stock_master(settings.stock_master_path)
                    if not stock_master.empty:
                        df["symbol"] = df["symbol"].astype(str)
                        stock_master["symbol"] = stock_master["symbol"].astype(str)
                        # Only merge if industry is not already present
                        if "industry" not in df.columns:
                            df = pd.merge(
                                df,
                                stock_master[["market", "symbol", "industry"]],
                                on=["market", "symbol"],
                                how="left",
                            )
                    elif "industry" not in df.columns:
                        df["industry"] = ""

                    # Sort by Strategy, Industry, Close
                    sort_cols = []
                    if "strategy" in df.columns:
                        sort_cols.append("strategy")
                    if "industry" in df.columns:
                        sort_cols.append("industry")
                    if "close" in df.columns:
                        sort_cols.append("close")
                    if sort_cols:
                        ascending = [True] * len(sort_cols)
                        if "close" in sort_cols:
                            ascending[sort_cols.index("close")] = False
                        df = df.sort_values(by=sort_cols, ascending=ascending)

                    market_map = {"TWSE": "上市", "TPEX": "上櫃"}
                    df["market"] = df["market"].map(lambda x: market_map.get(x, x))

                    disp_columns = [
                        "date",
                        "strategy",
                        "direction",
                        "market",
                        "symbol",
                        "name",
                        "industry",
                        "close",
                        "volume",
                        "score",
                    ]
                    for col in disp_columns:
                        if col not in df.columns:
                            df[col] = ""

                    df = df[disp_columns]
                    df.columns = [
                        "日期",
                        "策略代號",
                        "方向",
                        "市場",
                        "代號",
                        "名稱",
                        "產業",
                        "收盤價",
                        "成交量",
                        "符合度",
                    ]
                    df["方向"] = (
                        df["方向"].map({"long": "做多", "short": "做空"}).fillna(df["方向"])
                    )
                    df["符合度"] = pd.to_numeric(df["符合度"], errors="coerce").apply(
                        lambda x: f"{x:.0%}" if pd.notna(x) else ""
                    )
                    print(df.to_string(index=False))

            elif args.inspect_command == "logs":
                if args.type == "jobs":
                    data = get_job_logs(session, limit=args.limit)
                    if not data:
                        print("No job logs found.")
                    else:
                        df = pd.DataFrame(data)
                        print(df[["start", "job", "status", "in", "out", "error"]])
                else:
                    data = get_quarantine_logs(session, limit=args.limit)
                    if not data:
                        print("No quarantine logs found.")
                    else:
                        df = pd.DataFrame(data)
                        print(df[df.columns[:8]])  # Show first few columns

            elif args.inspect_command == "intraday-trades":
                from sqlalchemy import desc, select

                from sentinel.models import IntradayTrade

                stmt = select(IntradayTrade).order_by(desc(IntradayTrade.entry_date)).limit(50)
                trades = session.execute(stmt).scalars().all()
                if not trades:
                    print("No intraday trade logs found.")
                    return 0

                data = [
                    {
                        "entry_date": t.entry_date,
                        "market": t.market,
                        "symbol": t.symbol,
                        "entry": t.entry_price,
                        "exit": t.exit_price,
                        "p/l": t.profit_loss,
                        "status": t.status,
                    }
                    for t in trades
                ]
                df = pd.DataFrame(data)

                # Merge with stock master for Chinese names
                stock_master = load_stock_master(settings.stock_master_path)
                if not stock_master.empty:
                    df["symbol"] = df["symbol"].astype(str)
                    stock_master["symbol"] = stock_master["symbol"].astype(str)
                    df = pd.merge(
                        df,
                        stock_master[["market", "symbol", "name"]],
                        on=["market", "symbol"],
                        how="left",
                    )
                else:
                    df["name"] = ""

                # Rename and format for display
                df = df[["entry_date", "symbol", "name", "entry", "exit", "p/l", "status"]]
                df.columns = ["進場日期", "代號", "名稱", "進場價", "出場價", "報酬率", "狀態"]

                df["報酬率"] = df["報酬率"].apply(lambda x: f"{x:.2%}" if pd.notna(x) else "")
                df["狀態"] = (
                    df["狀態"].map({"open": "持有中", "closed": "已平倉"}).fillna(df["狀態"])
                )

                # Calculate Summary Statistics
                closed_df = df[df["狀態"] == "已平倉"].copy()
                summary_str = ""
                if not closed_df.empty:
                    # Ensure 報酬率 is numeric for calculation
                    numeric_pl = (
                        pd.to_numeric(closed_df["報酬率"].str.replace("%", ""), errors="coerce")
                        / 100
                    )
                    win_rate = (numeric_pl > 0).mean()
                    avg_pl = numeric_pl.mean()
                    total_trades = len(closed_df)
                    win_count = (numeric_pl > 0).sum()
                    loss_count = (numeric_pl <= 0).sum()

                    summary_str = (
                        f"📈 績效總結 (Summary Statistics - 已平倉):\n"
                        f"--------------------------------------------------------------------------------\n"
                        f"總交易次數: {total_trades} | 勝場: {win_count} | 敗場: {loss_count}\n"
                        f"勝率: {win_rate:.2%} | 平均報酬率: {avg_pl:.2%}\n"
                    )

                pd.set_option("display.unicode.east_asian_width", True)
                print("\n" + "=" * 80)
                print("📋 模擬交易日誌 (Intraday Trade Logs)")
                print("=" * 80)
                if summary_str:
                    print(summary_str)
                    print("-" * 80)
                print(df.to_string(index=False))
                print("=" * 80 + "\n")

                if getattr(args, "export", False):
                    report_dir = Path("outputs/reports")
                    report_dir.mkdir(parents=True, exist_ok=True)
                    report_path = report_dir / f"intraday_trades_{date.today().isoformat()}.csv"
                    df.to_csv(report_path, index=False, encoding="utf-8-sig")
                    print(f"✅ 報表已匯出至: {report_path}")

        return 0

    if args.command == "check-stock":
        import json as _json

        dataset_path = args.dataset_path or settings.price_dataset_path
        signal_path = args.signal_path or settings.signal_config_path
        stock_master = load_stock_master(settings.stock_master_path)

        if not signal_path.exists():
            print(f"⚠️  找不到訊號設定檔：{signal_path}")
            return 1

        signals = _json.loads(signal_path.read_text(encoding="utf-8")).get("signals", [])

        prices = load_price_dataset(dataset_path)
        stock_prices = prices[prices["symbol"] == args.symbol].copy()
        if stock_prices.empty:
            print(f"⚠️  找不到股票代號 {args.symbol}，請確認 dataset 是否已同步。")
            return 1

        trading_date = (
            parse_iso_date(args.date)
            if args.date
            else pd.to_datetime(stock_prices["trading_date"]).dt.date.max()
        )

        enriched = compute_indicators(stock_prices)

        # 法人買賣超 enrichment（有設定資料庫才會生效；失敗不阻斷檢驗）
        check_database_url = args.database_url or settings.database_url
        if check_database_url and not enriched.empty:
            enriched = _apply_institutional_enrichment(
                enriched, create_db_engine(check_database_url)
            )

        stock_name = args.symbol
        if not stock_master.empty:
            match = stock_master[stock_master["symbol"] == args.symbol]
            if not match.empty:
                stock_name = f"{match.iloc[0]['name']} {args.symbol}"

        # Convert signals.json format → strategies format understood by scan_strategies
        from sentinel.strategies import scan_strategies

        runnable, not_runnable = [], []
        for sig in signals:
            params = sig.get("params", {})
            if (
                sig.get("requires_intraday")
                or sig.get("requires_market_breadth")
                or sig.get("requires_gap_detection")
                or not sig.get("is_active", True)
            ):
                not_runnable.append(sig)
                continue
            runnable.append(
                {
                    "strategy_id": sig["signal_id"],
                    "name": sig["name"],
                    "version": sig.get("version", "1.0.0"),
                    "description": sig.get("description", ""),
                    "is_active": True,
                    "params_json": {
                        "min_history_days": params.get("min_history_days", 25),
                        "direction": sig.get("direction", "long"),
                        "conditions": params.get("conditions", []),
                    },
                    "backtest": {},
                }
            )

        results = scan_strategies(enriched, trading_date, runnable) if runnable else pd.DataFrame()
        triggered = set(results["strategy_id"].tolist()) if not results.empty else set()

        def _cond_detail(signal_id: str) -> str:
            if results.empty:
                return ""
            row = results[results["strategy_id"] == signal_id]
            if row.empty:
                return ""
            conds = row.iloc[0].get("signals_json", {})
            if not isinstance(conds, dict):
                return ""
            lines = []
            for c in conds.get("conditions", []):
                mark = "✅" if c.get("passed") else "  "
                val, ref = c.get("value"), c.get("reference")
                val_str = (
                    f"{val:.2f}"
                    if isinstance(val, float)
                    else (str(val) if val is not None else "?")
                )
                ref_str = (
                    f"{ref:.2f}"
                    if isinstance(ref, float)
                    else (str(ref) if ref is not None else "?")
                )
                lines.append(
                    f"       {mark} {c.get('name','')}: {val_str} {c.get('operator','')} {ref_str}"
                )
            return "\n".join(lines)

        W = 62
        print("\n" + "╔" + "═" * W + "╗")
        title = f"  個股訊號檢驗 — {stock_name}  （{trading_date}）"
        print("║" + title.ljust(W) + "║")
        print("╚" + "═" * W + "╝")

        long_sigs = [s for s in runnable if s["params_json"].get("direction") == "long"]
        warn_sigs = [
            s for s in runnable if s["params_json"].get("direction") in ("warning", "short")
        ]

        if long_sigs:
            print("\n📈 做多進場訊號")
            print("─" * (W + 2))
            for s in long_sigs:
                sid = s["strategy_id"]
                hit = sid in triggered
                mark = "✅" if hit else "❌"
                print(f"  {mark} {s['name']}")
                detail = _cond_detail(sid)
                if detail:
                    print(detail)

        if warn_sigs:
            print("\n⚠️  警示 / 出場訊號")
            print("─" * (W + 2))
            for s in warn_sigs:
                sid = s["strategy_id"]
                hit = sid in triggered
                mark = "🔴" if hit else "❌"
                print(f"  {mark} {s['name']}")
                detail = _cond_detail(sid)
                if detail:
                    print(detail)

        if not_runnable:
            print("\n⚙️  需盤中資料 / 待實作（無法自動檢驗）")
            print("─" * (W + 2))
            for s in not_runnable:
                reason = ""
                if s.get("requires_intraday"):
                    reason = f"需 {s.get('intraday_interval','盤中')} 資料"
                elif s.get("requires_market_breadth"):
                    reason = "需大盤廣度資料"
                elif s.get("requires_gap_detection"):
                    reason = "缺口偵測邏輯待實作"
                elif not s.get("is_active", True):
                    reason = "人工規則"
                print(f"  ⚙️  {s['name']}  [{s.get('source_rule','')}]  — {reason}")

        print()
        return 0

    if args.command == "backfill-yahoo":
        from sentinel.providers import fetch_yahoo_historical

        start_date = parse_iso_date(args.start_date)
        end_date = parse_iso_date(args.end_date)
        markets = args.markets or ["TWSE", "TPEX"]
        database_url = args.database_url or settings.database_url
        engine = create_db_engine(database_url) if database_url else None
        if engine:
            create_schema(engine)

        stock_master = load_stock_master(settings.stock_master_path)
        dataset_path = settings.price_dataset_path
        existing_prices = load_price_dataset(dataset_path)

        total_fetched = 0
        for market in markets:
            market_stocks = stock_master[stock_master["market"] == market]
            if market_stocks.empty:
                print(f"⚠️  無法取得 {market} 的股票清單，跳過。")
                continue

            symbols = market_stocks["symbol"].astype(str).tolist()
            print(
                f"🔄 從 Yahoo Finance 補抓 {market} {start_date} ~ {end_date}（{len(symbols)} 支股票）..."
            )

            fetched = fetch_yahoo_historical(
                market=market,
                symbols=symbols,
                start_date=start_date,
                end_date=end_date,
            )

            if fetched.empty:
                print(f"⚠️  {market} 無資料回傳，請確認日期範圍是否為交易日。")
                continue

            # Fill names from stock master
            name_map = stock_master.set_index("symbol")["name"].to_dict()
            fetched["name"] = fetched["symbol"].map(name_map).fillna("")

            rows = len(fetched)
            total_fetched += rows
            print(f"✅ {market} 取得 {rows} 筆資料")

            existing_prices = upsert_prices(existing_prices, fetched)

            if engine:
                from sqlalchemy.orm import Session

                from sentinel.persistence import upsert_daily_prices

                with Session(engine) as session:
                    upsert_daily_prices(
                        session=session, prices=fetched, data_version=settings.data_version
                    )
                    session.commit()

        save_price_dataset(existing_prices, dataset_path)
        print(f"\n✅ 補抓完成，共 {total_fetched} 筆。已更新至 {dataset_path}")
        return 0

    if args.command == "sync":
        database_url = args.database_url or settings.database_url
        if not database_url:
            parser.error("--database-url is required or set TS_DATABASE_URL in the environment")

        engine = create_db_engine(database_url)
        create_schema(engine)

        from datetime import timedelta

        from sqlalchemy.orm import Session

        markets = args.markets or ["TWSE", "TPEX"]
        today = date.today()

        with Session(engine) as session:
            latest_dates = get_latest_dates_by_market(session)

        # 決定同步的起始日期：找所有市場中最舊的最後更新日
        # 如果某個市場沒資料，預設從 2024-01-01 開始
        relevant_latest_dates = [latest_dates.get(m) for m in markets if latest_dates.get(m)]

        if len(relevant_latest_dates) < len(markets):
            # 至少有一個市場沒資料
            start_date = date(2024, 1, 1)
        else:
            start_date = min(relevant_latest_dates) + timedelta(days=1)

        end_date = today

        if start_date > end_date:
            print(
                f"✅ 資料已是最新狀態 (最後日期: {max(relevant_latest_dates) if relevant_latest_dates else 'N/A'})"
            )
            return 0

        print(f"🔄 開始自動同步資料: {start_date} -> {end_date} (市場: {', '.join(markets)})")

        # 設定為 run 指令的參數，複用後面的 pipeline 邏輯
        args.start_date = start_date.isoformat()
        args.end_date = end_date.isoformat()
        args.trading_date = end_date.isoformat()
        args.markets = markets
        args.calendar_source_mode = "auto"
        args.price_source_mode = "auto"
        args.skip_indicators = False
        args.skip_strategies = not getattr(args, "scan", False)
        args.dataset_path = None
        args.output_dir = None
        args.data_version = None
        args.strategy_path = None
        # 繼續執行後面的 run 邏輯
        args.command = "run"

    if args.command == "backfill-aggregated-bars":
        database_url = args.database_url or settings.database_url
        if not database_url:
            parser.error("--database-url is required or set TS_DATABASE_URL in the environment")

        dataset_path = args.dataset_path or settings.price_dataset_path
        engine = create_db_engine(database_url)
        create_schema(engine)

        from sqlalchemy.orm import Session

        from sentinel.persistence import backfill_aggregated_bars

        prices = load_price_dataset(dataset_path)
        logger.info("backfill_aggregated_bars_started", extra={"rows": len(prices)})
        with Session(engine) as session:
            counts = backfill_aggregated_bars(session, prices)
            session.commit()
        logger.info("backfill_aggregated_bars_done", extra=counts)
        print(f"3D bars: {counts.get('daily_prices_3d', 0)} rows")
        print(f"47D bars: {counts.get('daily_prices_47d', 0)} rows")
        return 0

    if args.command != "run":
        parser.error(f"Unsupported command: {args.command}")

    start_date = parse_iso_date(args.start_date)
    end_date = parse_iso_date(args.end_date)
    trading_date = parse_iso_date(args.trading_date) if args.trading_date else end_date

    if start_date > end_date:
        parser.error("--start-date must be on or before --end-date")

    dataset_path = args.dataset_path or settings.price_dataset_path
    output_dir = args.output_dir or settings.output_dir
    data_version = args.data_version or settings.data_version
    database_url = args.database_url or settings.database_url
    markets = args.markets or ["TWSE"]
    run_id = uuid.uuid4().hex
    engine = create_db_engine(database_url) if database_url else None
    if engine:
        create_schema(engine)
    stock_master = load_stock_master(settings.stock_master_path)
    strategy_definitions = load_strategy_definitions(
        args.strategy_path or settings.strategy_config_path
    )

    logger.info(
        "pipeline_started",
        extra={
            "run_id": run_id,
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "trading_date": trading_date.isoformat(),
            "markets": markets,
            "database_enabled": bool(engine),
        },
    )

    if engine:
        start_job_run(engine=engine, run_id=run_id)

    try:
        official_trading_calendar = fetch_official_trading_calendar(
            start_date=start_date,
            end_date=end_date,
            markets=markets,
            settings=settings,
            source_mode=args.calendar_source_mode,
        )
        existing_prices = load_price_dataset(dataset_path)
        fetched_prices = fetch_prices(
            start_date=start_date,
            end_date=end_date,
            markets=markets,
            settings=settings,
            official_trading_calendar=official_trading_calendar,
            price_source_mode=args.price_source_mode,
            existing_prices=existing_prices,
        )
        validation_result = validate_daily_prices(fetched_prices, reference_prices=existing_prices)
        valid_prices = validation_result.valid_prices
        invalid_prices = validation_result.invalid_prices
        if not invalid_prices.empty:
            logger.warning(
                "invalid_daily_prices_quarantined",
                extra={
                    "run_id": run_id,
                    "rows": int(len(invalid_prices.index)),
                    "rules": sorted(
                        {
                            rule
                            for row_rules in invalid_prices["violations"].tolist()
                            for rule in row_rules
                        }
                    ),
                },
            )

        existing_prices = load_price_dataset(dataset_path)
        merged_prices = upsert_prices(existing_prices, valid_prices)
        save_price_dataset(merged_prices, dataset_path)

        if args.skip_indicators:
            logger.info("skipping_indicators_as_requested")
            enriched_prices = merged_prices.copy()
        else:
            # Limit historical data to 300 trading days per stock for indicator computation.
            # MA200 needs 200 days; 300 provides a safe buffer without processing all history.
            _indicator_cutoff = pd.Timestamp(trading_date) - pd.Timedelta(days=420)
            _indicator_prices = merged_prices[
                pd.to_datetime(merged_prices["trading_date"]) >= _indicator_cutoff
            ]
            logger.info(
                "indicator_lookback_trimmed",
                extra={"rows_full": len(merged_prices), "rows_trimmed": len(_indicator_prices)},
            )
            enriched_prices = compute_indicators(
                _indicator_prices,
                trading_date=trading_date,
                markets=markets,
                cache_dir=settings.resolved_indicator_cache_dir,
                calc_version=settings.indicator_calc_version,
            )

        # 法人買賣超 enrichment（資料庫有資料才會生效；失敗不阻斷掃描）
        if engine is not None and not enriched_prices.empty:
            enriched_prices = _apply_institutional_enrichment(enriched_prices, engine)

        if args.skip_strategies:
            logger.info("skipping_strategies_as_requested")
            scan_results = pd.DataFrame()  # Empty result
        else:
            scan_results = scan_strategy(
                enriched_prices, trading_date=trading_date, strategies=strategy_definitions
            )
            if args.direction:
                scan_results = scan_results[scan_results["direction"] == args.direction].copy()

            # Enrich with verification data from enriched_prices (ma20, prev_close)
            if not scan_results.empty:
                # Extract columns for current trading_date
                verif_data = enriched_prices[enriched_prices["trading_date"] == trading_date][
                    ["market", "symbol", "ma20", "prev_close"]
                ].copy()
                scan_results = pd.merge(
                    scan_results, verif_data, on=["market", "symbol"], how="left"
                )

            # Enrich with industry info
            if not scan_results.empty and not stock_master.empty:
                scan_results["symbol"] = scan_results["symbol"].astype(str)
                stock_master_copy = stock_master.copy()
                stock_master_copy["symbol"] = stock_master_copy["symbol"].astype(str)
                scan_results = pd.merge(
                    scan_results,
                    stock_master_copy[["market", "symbol", "industry"]],
                    on=["market", "symbol"],
                    how="left",
                )
            elif not scan_results.empty:
                scan_results["industry"] = "未知"

        observed_dates = {}
        if not valid_prices.empty:
            valid_prices["trading_date"] = pd.to_datetime(valid_prices["trading_date"]).dt.date
            for market_name, market_frame in valid_prices.groupby("market"):
                observed_dates[market_name] = set(market_frame["trading_date"].tolist())
        trading_calendar = build_trading_calendar(
            start_date=start_date,
            end_date=end_date,
            markets=markets,
            observed_dates=observed_dates,
            official_overrides=official_trading_calendar,
        )
        completeness_universe_frames = []
        if not merged_prices.empty:
            completeness_universe_frames.append(merged_prices)
        if not invalid_prices.empty:
            completeness_universe_frames.append(
                invalid_prices[
                    [column for column in merged_prices.columns if column in invalid_prices.columns]
                ]
            )
        completeness_universe = (
            pd.concat(completeness_universe_frames, ignore_index=True)
            if completeness_universe_frames
            else merged_prices
        )
        completeness_summary = build_run_completeness_summary(
            universe_prices=completeness_universe,
            valid_prices=valid_prices,
            invalid_prices=invalid_prices,
            trading_calendar=trading_calendar,
            markets=markets,
            stock_master=stock_master,
        )
        artifacts = save_results(
            scan_results=scan_results,
            output_dir=output_dir,
            run_id=run_id,
            trading_date=trading_date,
            data_version=data_version,
            extra_metadata={"completeness": completeness_summary},
        )

        persisted_counts = {}
        if engine:
            indicator_scope = (
                enriched_prices[
                    enriched_prices["trading_date"].isin(
                        pd.to_datetime(valid_prices["trading_date"]).dt.date.tolist()
                    )
                ].copy()
                if not valid_prices.empty
                else enriched_prices.iloc[0:0].copy()
            )
            persisted_counts = persist_pipeline_results(
                engine=engine,
                prices=valid_prices,
                indicators=indicator_scope,
                scan_results=scan_results,
                trading_calendar=trading_calendar,
                data_quarantine=invalid_prices,
                run_id=run_id,
                trading_date=trading_date,
                data_version=data_version,
                strategy_definitions=strategy_definitions,
            )
            finish_job_run(
                engine=engine,
                run_id=run_id,
                status="success",
                rows_in=int(len(fetched_prices.index)),
                rows_out=int(len(scan_results.index)),
            )

        logger.info(
            "pipeline_finished",
            extra={
                "run_id": run_id,
                "rows_fetched": int(len(fetched_prices.index)),
                "rows_quarantined": int(len(invalid_prices.index)),
                "rows_in_dataset": int(len(merged_prices.index)),
                "signals": int(len(scan_results.index)),
                "completeness": completeness_summary,
                "csv_path": str(artifacts["csv"]),
                "json_path": str(artifacts["json"]),
                "md_path": str(artifacts["md"]),
                "tradingview_path": str(artifacts["tradingview"]),
                "persisted_counts": persisted_counts,
            },
        )

        print("\n" + "=" * 60)
        print("📊 執行完畢 - 策略掃描結果")
        print("=" * 60)
        print(f"📄 掃描結果 (MD): {artifacts['md']}")
        pd.set_option("display.unicode.east_asian_width", True)
        if not scan_results.empty:
            disp_scan = scan_results.copy()
            if stock_master is not None and not stock_master.empty:
                disp_scan["symbol"] = disp_scan["symbol"].astype(str)
                stock_master["symbol"] = stock_master["symbol"].astype(str)
                # Only merge if industry is not already present
                if "industry" not in disp_scan.columns:
                    disp_scan = pd.merge(
                        disp_scan,
                        stock_master[["market", "symbol", "industry"]],
                        on=["market", "symbol"],
                        how="left",
                    )
            elif "industry" not in disp_scan.columns:
                disp_scan["industry"] = ""

            # Sort by Strategy, Industry, Close
            sort_cols = []
            if "strategy_name" in disp_scan.columns:
                sort_cols.append("strategy_name")
            if "industry" in disp_scan.columns:
                sort_cols.append("industry")
            if "close" in disp_scan.columns:
                sort_cols.append("close")
            if sort_cols:
                ascending = [True] * len(sort_cols)
                if "close" in sort_cols:
                    ascending[sort_cols.index("close")] = False
                disp_scan = disp_scan.sort_values(by=sort_cols, ascending=ascending)

            market_map = {"TWSE": "上市", "TPEX": "上櫃"}
            disp_scan["market"] = disp_scan["market"].map(lambda x: market_map.get(x, x))

            disp_columns = [
                "trading_date",
                "strategy_name",
                "direction",
                "market",
                "symbol",
                "name",
                "industry",
                "close",
                "score",
            ]
            for col in disp_columns:
                if col not in disp_scan.columns:
                    disp_scan[col] = ""

            disp_scan = disp_scan[disp_columns]
            disp_scan.columns = [
                "日期",
                "策略名稱",
                "方向",
                "市場",
                "代號",
                "名稱",
                "產業",
                "收盤價",
                "符合度",
            ]
            disp_scan["方向"] = (
                disp_scan["方向"].map({"long": "做多", "short": "做空"}).fillna(disp_scan["方向"])
            )
            disp_scan["符合度"] = pd.to_numeric(disp_scan["符合度"], errors="coerce").apply(
                lambda x: f"{x:.0%}" if pd.notna(x) else ""
            )
            print(disp_scan.to_string(index=False))
        else:
            print("無符合策略的股票。")
        print("=" * 60 + "\n")

        return 0
    except Exception as exc:
        if engine:
            finish_job_run(
                engine=engine,
                run_id=run_id,
                status="failed",
                error_summary=str(exc)[:1000],
            )
        logger.error("pipeline_failed", extra={"run_id": run_id, "error": str(exc)})
        raise


if __name__ == "__main__":
    sys.exit(main())
