"""盤中（intraday）相關指令：快照、明日之星掃描、模擬交易與排程器。"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd
from sqlalchemy.orm import Session

from sentinel.cli.common import MARKET_LABELS, create_engine_with_schema, require_database_url
from sentinel.config import Settings
from sentinel.datasources.minute_bars import import_minute_bars_csv
from sentinel.domain.models import Stock
from sentinel.intraday.engine import run_tomorrow_star_scan
from sentinel.intraday.indicators import calculate_intraday_win_rates
from sentinel.intraday.snapshots import capture_intraday_snapshot
from sentinel.intraday.trades import (
    add_manual_intraday_trade,
    clear_intraday_trades,
    monitor_and_close_intraday_trades,
    update_intraday_trades,
)
from sentinel.storage.engine import create_db_engine


def register(subparsers: argparse._SubParsersAction) -> None:
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
        help="Daily gain threshold (0.05 targets 5%%+ gains).",
    )
    update_intraday_parser.add_argument(
        "--min-samples",
        type=int,
        default=5,
        help="Minimum number of samples required to calculate win rate.",
    )
    update_intraday_parser.set_defaults(handler=cmd_update_intraday_stats)

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
    capture_snapshot_parser.set_defaults(handler=cmd_capture_intraday_snapshot)

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
        help="Daily gain threshold (default: 0.075 for 7.5%%+).",
    )
    intraday_run_parser.add_argument(
        "--notify-telegram",
        action="store_true",
        help="Send results to Telegram Channel.",
    )
    intraday_run_parser.set_defaults(handler=cmd_run_intraday)

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
    update_trades_parser.set_defaults(handler=cmd_update_intraday_trades)

    monitor_trades_parser = subparsers.add_parser(
        "monitor-intraday-trades", help="Monitor open trades for 2%% SL/TP thresholds"
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
    monitor_trades_parser.set_defaults(handler=cmd_monitor_intraday_trades)

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
    add_trade_parser.set_defaults(handler=cmd_add_intraday_trade)

    clear_trades_parser = subparsers.add_parser(
        "clear-intraday-trades", help="Clear all simulated intraday trade records"
    )
    clear_trades_parser.add_argument(
        "--database-url",
        help="SQLAlchemy database URL. Defaults to TS_DATABASE_URL from environment.",
    )
    clear_trades_parser.set_defaults(handler=cmd_clear_intraday_trades)

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
    import_bars_parser.set_defaults(handler=cmd_import_minute_bars)

    scheduler_parser = subparsers.add_parser(
        "scheduler", help="Start the automated intraday strategy scheduler"
    )
    scheduler_parser.add_argument(
        "--database-url",
        help="SQLAlchemy database URL. Defaults to TS_DATABASE_URL from environment.",
    )
    scheduler_parser.set_defaults(handler=cmd_scheduler)


def cmd_update_intraday_stats(
    args: argparse.Namespace, *, settings: Settings, parser: argparse.ArgumentParser
) -> int:
    database_url = require_database_url(args, settings, parser)
    engine = create_engine_with_schema(database_url)  # Ensure new tables exist

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


def cmd_capture_intraday_snapshot(
    args: argparse.Namespace, *, settings: Settings, parser: argparse.ArgumentParser
) -> int:
    database_url = require_database_url(args, settings, parser)
    engine = create_engine_with_schema(database_url)

    with Session(engine) as session:
        print(f"Capturing intraday snapshot at {args.time} for top {args.top} stocks...")
        count = capture_intraday_snapshot(session, args.time, top_n=args.top)
        print(f"Successfully captured {count} snapshots.")
        return 0


def cmd_run_intraday(
    args: argparse.Namespace, *, settings: Settings, parser: argparse.ArgumentParser
) -> int:
    database_url = require_database_url(args, settings, parser)
    engine = create_engine_with_schema(database_url)

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
            df["market"] = df["market"].map(lambda x: MARKET_LABELS.get(x, x))
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


def cmd_update_intraday_trades(
    args: argparse.Namespace, *, settings: Settings, parser: argparse.ArgumentParser
) -> int:
    database_url = require_database_url(args, settings, parser)
    engine = create_engine_with_schema(database_url)

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


def cmd_monitor_intraday_trades(
    args: argparse.Namespace, *, settings: Settings, parser: argparse.ArgumentParser
) -> int:
    database_url = require_database_url(args, settings, parser)
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


def cmd_add_intraday_trade(
    args: argparse.Namespace, *, settings: Settings, parser: argparse.ArgumentParser
) -> int:
    database_url = require_database_url(args, settings, parser)
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


def cmd_clear_intraday_trades(
    args: argparse.Namespace, *, settings: Settings, parser: argparse.ArgumentParser
) -> int:
    database_url = require_database_url(args, settings, parser)
    engine = create_db_engine(database_url)

    with Session(engine) as session:
        count = clear_intraday_trades(session)
        print(f"Successfully cleared {count} intraday trade records.")
        return 0


def cmd_import_minute_bars(
    args: argparse.Namespace, *, settings: Settings, parser: argparse.ArgumentParser
) -> int:
    intraday_url = args.intraday_database_url or settings.intraday_database_url
    if not intraday_url:
        parser.error("--intraday-database-url is required or set TS_INTRADAY_DATABASE_URL")

    csv_path = args.csv
    if not csv_path.exists():
        parser.error(f"CSV file not found: {csv_path}")

    intraday_engine = create_engine_with_schema(intraday_url)

    # 獲取主表中的代號-市場映射，以修正 CSV 中不可靠的 exchange 標籤
    database_url = args.database_url or settings.database_url
    symbol_market_map = {}
    if database_url:
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


def cmd_scheduler(
    args: argparse.Namespace, *, settings: Settings, parser: argparse.ArgumentParser
) -> int:
    database_url = require_database_url(args, settings, parser)

    from sentinel.intraday.scheduler import IntradayScheduler

    scheduler = IntradayScheduler(database_url)
    scheduler.start()
    return 0
