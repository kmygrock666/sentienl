"""inspect 指令：檢視資料庫狀態、掃描結果、任務日誌與模擬交易紀錄。"""

from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path

import pandas as pd
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from sentinel.analysis.strategies import load_strategy_definitions
from sentinel.cli.common import MARKET_LABELS, require_database_url
from sentinel.config import Settings
from sentinel.datasources.stock_master import load_stock_master
from sentinel.domain.models import IntradayTrade
from sentinel.storage.engine import create_db_engine
from sentinel.storage.repositories.inspect_queries import (
    get_completeness,
    get_data_status,
    get_job_logs,
    get_quarantine_logs,
    get_scan_results,
)
from sentinel.utils import parse_iso_date

TABLE_DESCRIPTIONS = {
    "daily_prices": "日成交價",
    "technical_indicators": "技術指標",
    "scan_results": "策略掃描結果",
    "trading_calendar": "交易日曆",
    "institutional_flows": "三大法人買賣超",
    "margin_balances": "融資融券餘額",
    "intraday_snapshots": "日內量能快照",
    "intraday_trades": "日內模擬交易紀錄",
}


def register(subparsers: argparse._SubParsersAction) -> None:
    inspect_parser = subparsers.add_parser("inspect", help="Inspect database state and results")
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
        inspect_subparsers.choices.get("status"),
        completeness_parser,
        results_parser,
        logs_parser,
        inspect_subparsers.choices.get("intraday-trades"),
    ]:
        if p:
            p.add_argument("--database-url", help="SQLAlchemy database URL")

    inspect_parser.set_defaults(handler=cmd_inspect)


def cmd_inspect(
    args: argparse.Namespace, *, settings: Settings, parser: argparse.ArgumentParser
) -> int:
    database_url = require_database_url(args, settings, parser)
    engine = create_db_engine(database_url)

    with Session(engine) as session:
        if args.inspect_command == "status":
            _print_status(session)
        elif args.inspect_command == "completeness":
            _print_completeness(session, parse_iso_date(args.date))
        elif args.inspect_command == "results":
            exit_code = _print_results(session, args, settings)
            if exit_code is not None:
                return exit_code
        elif args.inspect_command == "logs":
            _print_logs(session, args)
        elif args.inspect_command == "intraday-trades":
            exit_code = _print_intraday_trades(session, args, settings)
            if exit_code is not None:
                return exit_code

    return 0


def _print_status(session: Session) -> None:
    data = get_data_status(session)

    print("\n" + "=" * 90)
    print(
        f"{'資料表 (Table Name)':<35} | {'最舊 (Min)':<12} | {'最新 (Max)':<12} | {'總筆數 (Records)':>13}"
    )
    print("-" * 90)
    for table_name, status in data.items():
        desc_label = TABLE_DESCRIPTIONS.get(table_name, "")
        label = f"{table_name} ({desc_label})" if desc_label else table_name
        print(
            f"{label:<35} | {status['earliest']:<12} | {status['latest']:<12} | {status['count']:>13,}"
        )
    print("=" * 90 + "\n")


def _print_completeness(session: Session, target_date: date) -> None:
    data = get_completeness(session, target_date)
    # Simplified output for terminal
    print(f"Date: {data['date']}")
    print(f"Ratio: {data['ratio']:.2%} ({data['actual']}/{data['expected']})")
    if data["missing"]:
        print("\nMissing Stocks:")
        for m in data["missing"]:
            print(f"  - {m['market']}:{m['symbol']}")


def _print_results(session: Session, args: argparse.Namespace, settings: Settings):
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
        return None

    pd.set_option("display.unicode.east_asian_width", True)
    df = pd.DataFrame(data)

    strategy_defs = load_strategy_definitions(settings.strategy_config_path)
    strategy_dir_map = {
        s["strategy_id"]: s.get("params_json", {}).get("direction", "long") for s in strategy_defs
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

    df["market"] = df["market"].map(lambda x: MARKET_LABELS.get(x, x))

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
    df["方向"] = df["方向"].map({"long": "做多", "short": "做空"}).fillna(df["方向"])
    df["符合度"] = pd.to_numeric(df["符合度"], errors="coerce").apply(
        lambda x: f"{x:.0%}" if pd.notna(x) else ""
    )
    print(df.to_string(index=False))
    return None


def _print_logs(session: Session, args: argparse.Namespace) -> None:
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


def _print_intraday_trades(session: Session, args: argparse.Namespace, settings: Settings):
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
    df["狀態"] = df["狀態"].map({"open": "持有中", "closed": "已平倉"}).fillna(df["狀態"])

    # Calculate Summary Statistics
    closed_df = df[df["狀態"] == "已平倉"].copy()
    summary_str = ""
    if not closed_df.empty:
        # Ensure 報酬率 is numeric for calculation
        numeric_pl = pd.to_numeric(closed_df["報酬率"].str.replace("%", ""), errors="coerce") / 100
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
    return None
