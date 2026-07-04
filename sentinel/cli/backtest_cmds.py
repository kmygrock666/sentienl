"""backtest 指令：解析參數、呼叫回測服務並輸出結果報表。"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from sentinel.cli.common import MARKET_LABELS
from sentinel.config import Settings
from sentinel.db import create_db_engine, create_schema
from sentinel.services.backtest_service import (
    BacktestJobReport,
    SymbolNotInDatasetError,
    run_backtest_job,
)
from sentinel.stock_master import load_stock_master
from sentinel.strategies import load_strategy_definitions
from sentinel.utils import parse_iso_date


def register(subparsers: argparse._SubParsersAction) -> None:
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
    backtest_parser.set_defaults(handler=cmd_backtest)


def cmd_backtest(
    args: argparse.Namespace, *, settings: Settings, parser: argparse.ArgumentParser
) -> int:
    start_date = parse_iso_date(args.start_date)
    end_date = parse_iso_date(args.end_date)
    if start_date > end_date:
        parser.error("--start-date must be on or before --end-date")

    dataset_path = args.dataset_path or settings.price_dataset_path
    output_dir = args.output_dir or settings.output_dir
    database_url = args.database_url or settings.database_url
    intraday_url = args.intraday_database_url or settings.intraday_database_url

    if args.execution_model == "minute_bar" and (not database_url or not intraday_url):
        parser.error(
            "minute_bar execution model requires both --database-url and --intraday-database-url (or TS_DATABASE_URL and TS_INTRADAY_DATABASE_URL)"
        )

    engine = create_db_engine(database_url) if database_url else None
    intraday_engine = create_db_engine(intraday_url) if intraday_url else None

    if engine:
        create_schema(engine)
    if intraday_engine:
        create_schema(intraday_engine)

    strategy_definitions = load_strategy_definitions(
        args.strategy_path or settings.strategy_config_path
    )

    try:
        report = run_backtest_job(
            engine=engine,
            intraday_engine=intraday_engine,
            start_date=start_date,
            end_date=end_date,
            markets=args.markets,
            dataset_path=dataset_path,
            output_dir=output_dir,
            strategy_definitions=strategy_definitions,
            execution_model=args.execution_model,
            strategy_mode=args.strategy_mode,
            benchmark_symbol=args.benchmark_symbol,
            symbol=args.symbol,
            initial_capital=args.initial_capital,
            position_size=args.position_size,
        )
    except SymbolNotInDatasetError:
        print(f"⚠️ No data found for symbol: {args.symbol} in the dataset.")
        return 0

    _print_backtest_summary(report, settings)
    return 0


def _print_backtest_summary(report: BacktestJobReport, settings: Settings) -> None:
    reports = report.reports
    trades = report.trades
    artifacts = report.artifacts

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

        disp_trades["market"] = disp_trades["market"].map(lambda x: MARKET_LABELS.get(x, x))

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
