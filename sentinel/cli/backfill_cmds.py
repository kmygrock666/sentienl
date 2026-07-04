"""歷史資料補抓指令：backfill-yahoo、backfill-aggregated-bars。"""

from __future__ import annotations

import argparse
from pathlib import Path

from sqlalchemy.orm import Session

from sentinel.cli.common import create_engine_with_schema, require_database_url
from sentinel.config import Settings
from sentinel.logging_utils import get_logger
from sentinel.services.backfill_service import backfill_yahoo_prices
from sentinel.storage import load_price_dataset
from sentinel.storage.engine import create_db_engine, create_schema
from sentinel.storage.persistence import backfill_aggregated_bars
from sentinel.utils import parse_iso_date

_logger = get_logger(__name__)


def register(subparsers: argparse._SubParsersAction) -> None:
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
    backfill_agg_parser.set_defaults(handler=cmd_backfill_aggregated_bars)

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
    yahoo_parser.set_defaults(handler=cmd_backfill_yahoo)


def cmd_backfill_aggregated_bars(
    args: argparse.Namespace, *, settings: Settings, parser: argparse.ArgumentParser
) -> int:
    database_url = require_database_url(args, settings, parser)
    dataset_path = args.dataset_path or settings.price_dataset_path
    engine = create_engine_with_schema(database_url)

    prices = load_price_dataset(dataset_path)
    _logger.info("backfill_aggregated_bars_started", extra={"rows": len(prices)})
    with Session(engine) as session:
        counts = backfill_aggregated_bars(session, prices)
        session.commit()
    _logger.info("backfill_aggregated_bars_done", extra=counts)
    print(f"3D bars: {counts.get('daily_prices_3d', 0)} rows")
    print(f"47D bars: {counts.get('daily_prices_47d', 0)} rows")
    return 0


def cmd_backfill_yahoo(
    args: argparse.Namespace, *, settings: Settings, parser: argparse.ArgumentParser
) -> int:
    start_date = parse_iso_date(args.start_date)
    end_date = parse_iso_date(args.end_date)
    markets = args.markets or ["TWSE", "TPEX"]
    database_url = args.database_url or settings.database_url
    engine = create_db_engine(database_url) if database_url else None
    if engine:
        create_schema(engine)

    total_fetched = backfill_yahoo_prices(
        settings=settings,
        engine=engine,
        markets=markets,
        start_date=start_date,
        end_date=end_date,
        report=print,
    )
    print(f"\n✅ 補抓完成，共 {total_fetched} 筆。已更新至 {settings.price_dataset_path}")
    return 0
