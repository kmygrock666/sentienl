"""掃描相關指令：run（完整管線）、sync（增量同步）、check-stock（個股訊號檢驗）。"""

from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path
from typing import Dict, Optional

import pandas as pd

from sentinel.cli.common import MARKET_LABELS
from sentinel.config import Settings
from sentinel.db import create_db_engine, create_schema
from sentinel.pipeline import compute_indicators
from sentinel.services.enrichment import apply_institutional_enrichment
from sentinel.services.scan_service import DailyScanReport, run_daily_scan
from sentinel.services.signal_check import convert_signals_to_strategies
from sentinel.services.sync_service import build_sync_plan
from sentinel.stock_master import load_stock_master
from sentinel.storage import load_price_dataset
from sentinel.strategies import load_strategy_definitions, scan_strategies
from sentinel.utils import parse_iso_date


def register(subparsers: argparse._SubParsersAction) -> None:
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
    run_parser.set_defaults(handler=cmd_run)

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
    sync_parser.set_defaults(handler=cmd_sync)

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
    check_parser.set_defaults(handler=cmd_check_stock)


def cmd_run(
    args: argparse.Namespace, *, settings: Settings, parser: argparse.ArgumentParser
) -> int:
    start_date = parse_iso_date(args.start_date)
    end_date = parse_iso_date(args.end_date)
    trading_date = parse_iso_date(args.trading_date) if args.trading_date else end_date

    if start_date > end_date:
        parser.error("--start-date must be on or before --end-date")

    database_url = args.database_url or settings.database_url
    engine = create_db_engine(database_url) if database_url else None
    if engine:
        create_schema(engine)

    return _execute_scan(
        settings=settings,
        engine=engine,
        start_date=start_date,
        end_date=end_date,
        trading_date=trading_date,
        markets=args.markets or ["TWSE"],
        dataset_path=args.dataset_path or settings.price_dataset_path,
        output_dir=args.output_dir or settings.output_dir,
        data_version=args.data_version or settings.data_version,
        calendar_source_mode=args.calendar_source_mode,
        price_source_mode=args.price_source_mode,
        strategy_path=args.strategy_path,
        skip_indicators=args.skip_indicators,
        skip_strategies=args.skip_strategies,
        direction=args.direction,
    )


def cmd_sync(
    args: argparse.Namespace, *, settings: Settings, parser: argparse.ArgumentParser
) -> int:
    database_url = args.database_url or settings.database_url
    if not database_url:
        parser.error("--database-url is required or set TS_DATABASE_URL in the environment")

    engine = create_db_engine(database_url)
    create_schema(engine)

    markets = args.markets or ["TWSE", "TPEX"]
    plan = build_sync_plan(engine, markets)

    if plan.up_to_date:
        latest_summary = ", ".join(
            f"{m}={plan.latest_dates.get(m)}" for m in plan.market_start_dates
        )
        print(f"✅ 資料已是最新狀態 ({latest_summary})")
        return 0

    market_summary = ", ".join(f"{m}:{plan.market_start_dates[m]}" for m in plan.market_start_dates)
    print(f"🔄 開始自動同步資料 -> {plan.end_date} (市場起點: {market_summary})")

    return _execute_scan(
        settings=settings,
        engine=engine,
        start_date=plan.start_date,
        end_date=plan.end_date,
        trading_date=plan.end_date,
        markets=markets,
        dataset_path=settings.price_dataset_path,
        output_dir=settings.output_dir,
        data_version=settings.data_version,
        calendar_source_mode="auto",
        price_source_mode="auto",
        strategy_path=None,
        skip_indicators=False,
        skip_strategies=not args.scan,
        direction=args.direction,
        market_start_dates=plan.market_start_dates,
    )


def _execute_scan(
    *,
    settings: Settings,
    engine,
    start_date: date,
    end_date: date,
    trading_date: date,
    markets: list,
    dataset_path: Path,
    output_dir: Path,
    data_version: str,
    calendar_source_mode: str,
    price_source_mode: str,
    strategy_path: Optional[Path],
    skip_indicators: bool,
    skip_strategies: bool,
    direction: Optional[str],
    market_start_dates: Optional[Dict[str, date]] = None,
) -> int:
    stock_master = load_stock_master(settings.stock_master_path)
    strategy_definitions = load_strategy_definitions(strategy_path or settings.strategy_config_path)

    report = run_daily_scan(
        settings=settings,
        engine=engine,
        start_date=start_date,
        end_date=end_date,
        trading_date=trading_date,
        markets=markets,
        dataset_path=dataset_path,
        output_dir=output_dir,
        data_version=data_version,
        calendar_source_mode=calendar_source_mode,
        price_source_mode=price_source_mode,
        strategy_definitions=strategy_definitions,
        stock_master=stock_master,
        skip_indicators=skip_indicators,
        skip_strategies=skip_strategies,
        direction=direction,
        market_start_dates=market_start_dates,
    )

    _print_scan_summary(report, stock_master)
    return 0


def _print_scan_summary(report: DailyScanReport, stock_master: pd.DataFrame) -> None:
    scan_results = report.scan_results
    artifacts = report.artifacts

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

        disp_scan["market"] = disp_scan["market"].map(lambda x: MARKET_LABELS.get(x, x))

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


def cmd_check_stock(
    args: argparse.Namespace, *, settings: Settings, parser: argparse.ArgumentParser
) -> int:
    dataset_path = args.dataset_path or settings.price_dataset_path
    signal_path = args.signal_path or settings.signal_config_path
    stock_master = load_stock_master(settings.stock_master_path)

    if not signal_path.exists():
        print(f"⚠️  找不到訊號設定檔：{signal_path}")
        return 1

    signals = json.loads(signal_path.read_text(encoding="utf-8")).get("signals", [])

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
        enriched = apply_institutional_enrichment(enriched, create_db_engine(check_database_url))

    stock_name = args.symbol
    if not stock_master.empty:
        match = stock_master[stock_master["symbol"] == args.symbol]
        if not match.empty:
            stock_name = f"{match.iloc[0]['name']} {args.symbol}"

    # Convert signals.json format → strategies format understood by scan_strategies
    runnable, not_runnable = convert_signals_to_strategies(signals)

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
                f"{val:.2f}" if isinstance(val, float) else (str(val) if val is not None else "?")
            )
            ref_str = (
                f"{ref:.2f}" if isinstance(ref, float) else (str(ref) if ref is not None else "?")
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
    warn_sigs = [s for s in runnable if s["params_json"].get("direction") in ("warning", "short")]

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
