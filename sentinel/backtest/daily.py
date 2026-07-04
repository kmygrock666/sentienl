from __future__ import annotations

import json
from collections.abc import Iterable
from datetime import date, datetime
from pathlib import Path
from typing import Optional

import pandas as pd

from sentinel.analysis.strategies import scan_strategies


def run_backtest(
    prices_with_indicators: pd.DataFrame,
    strategies: Iterable[dict],
    start_date: date,
    end_date: date,
    benchmark_symbol: Optional[str] = None,
    initial_capital: Optional[float] = None,
    position_size: float = 100000,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    full_frame = prices_with_indicators.copy()
    if full_frame.empty:
        return pd.DataFrame(), pd.DataFrame()

    full_frame["trading_date"] = pd.to_datetime(full_frame["trading_date"]).dt.date
    evaluation_frame = full_frame[
        (full_frame["trading_date"] >= start_date) & (full_frame["trading_date"] <= end_date)
    ].copy()
    if evaluation_frame.empty:
        return pd.DataFrame(), pd.DataFrame()

    trading_dates = sorted(evaluation_frame["trading_date"].dropna().unique().tolist())
    all_signals = []
    for trading_date in trading_dates:
        daily_signals = scan_strategies(
            full_frame, trading_date=trading_date, strategies=strategies
        )
        if daily_signals.empty:
            continue
        all_signals.append(daily_signals)

    signal_frame = pd.concat(all_signals, ignore_index=True) if all_signals else pd.DataFrame()
    if signal_frame.empty:
        return pd.DataFrame(), pd.DataFrame()

    # 4. Simulate Trades
    all_strategy_trades = []
    for strategy in strategies:
        if not strategy.get("is_active", True):
            continue

        # Skip strategies meant for minute bar execution
        if strategy.get("backtest", {}).get("execution_model_version") == "minute_bar_execution":
            continue

        strategy_id = strategy["strategy_id"]
        holding_days_val = strategy.get("backtest", {}).get("holding_period_days", 5)
        holding_period_days = int(holding_days_val) if holding_days_val is not None else 5

        strategy_signals = signal_frame[signal_frame["strategy_id"] == strategy_id].copy()
        if strategy_signals.empty:
            continue

        # pre-calculate candidate trades (unlimited)
        candidates = []
        for signal in strategy_signals.to_dict(orient="records"):
            symbol_history = prices_with_indicators[
                (prices_with_indicators["market"] == signal["market"])
                & (prices_with_indicators["symbol"] == signal["symbol"])
            ].copy()
            symbol_history["trading_date"] = pd.to_datetime(symbol_history["trading_date"]).dt.date
            symbol_history = (
                symbol_history[symbol_history["trading_date"] <= end_date]
                .sort_values("trading_date")
                .reset_index(drop=True)
            )

            signal_indices = symbol_history.index[
                symbol_history["trading_date"] == signal["trading_date"]
            ]
            if len(signal_indices) == 0:
                continue

            signal_index = int(signal_indices[-1])
            entry_index = signal_index + 1
            if entry_index >= len(symbol_history):
                continue

            # Dynamic Exit Check
            max_exit_index = signal_index + holding_period_days
            actual_exit_index = max_exit_index
            for i in range(entry_index, max_exit_index + 1):
                if i >= len(symbol_history):
                    actual_exit_index = len(symbol_history) - 1
                    break

                curr_row = symbol_history.iloc[i]
                prev_row = symbol_history.iloc[i - 1]
                prev_body_low = min(float(prev_row["open"]), float(prev_row["close"]))

                if float(curr_row["close"]) < prev_body_low:
                    actual_exit_index = i
                    break

            entry_row = symbol_history.iloc[entry_index]
            exit_row = symbol_history.iloc[actual_exit_index]
            entry_price = float(entry_row["open"])
            exit_price = float(exit_row["close"])
            trade_return = (exit_price / entry_price) - 1.0 if entry_price else 0.0

            candidates.append(
                {
                    "strategy_id": strategy_id,
                    "strategy_name": strategy["name"],
                    "symbol": signal["symbol"],
                    "name": signal["name"],
                    "market": signal["market"],
                    "signal_date": signal["trading_date"],
                    "entry_date": entry_row["trading_date"],
                    "exit_date": exit_row["trading_date"],
                    "entry_price": entry_price,
                    "exit_price": exit_price,
                    "holding_period_days": holding_period_days,
                    "trade_return": trade_return,
                    "execution_model_version": strategy.get("backtest", {}).get(
                        "execution_model_version",
                        "next_open_to_close",
                    ),
                }
            )

        # Apply Capital Constraints if needed
        if initial_capital is not None:
            # Sort by entry date then symbol (for consistent processing)
            candidates.sort(key=lambda x: (x["entry_date"], x["symbol"]))
            balance = initial_capital
            active_trades = []
            final_trades = []

            # Use all trading dates in the evaluation period
            all_dates = sorted(trading_dates)
            for d in all_dates:
                # 1. Check for exits TODAY
                still_active = []
                for t in active_trades:
                    if t["exit_date"] <= d:  # The money becomes available on the exit day
                        # Add profit (including principal)
                        balance += position_size * (1.0 + t["trade_return"])
                        t["balance"] = balance
                        final_trades.append(t)
                    else:
                        still_active.append(t)
                active_trades = still_active

                # 2. Check for entries TODAY
                todays_signals = [c for c in candidates if c["entry_date"] == d]
                for s in todays_signals:
                    if balance >= position_size:
                        balance -= position_size
                        active_trades.append(s)

            # Add any remaining active trades at the end of the backtest
            final_trades.extend(active_trades)
            all_strategy_trades.extend(final_trades)
        else:
            all_strategy_trades.extend(candidates)

    trade_frame = pd.DataFrame(all_strategy_trades)
    if trade_frame.empty:
        return pd.DataFrame(), pd.DataFrame()

    reports = []
    for strategy in strategies:
        strategy_trades = trade_frame[trade_frame["strategy_id"] == strategy["strategy_id"]].copy()
        if strategy_trades.empty:
            continue
        strategy_trades = strategy_trades.sort_values(["exit_date", "symbol"]).reset_index(
            drop=True
        )

        # Calculate Equity Curve
        if initial_capital is not None:
            # For capital-constrained: use trade PnL relative to initial capital
            # We treat each trade as a fixed allocation flow
            strategy_trades["pnl_dollars"] = strategy_trades["trade_return"] * position_size
            equity_absolute = initial_capital + strategy_trades["pnl_dollars"].cumsum()
            equity = equity_absolute / initial_capital
        else:
            # For unlimited (legacy): use cumulative compounding of 100% position
            # This often leads to unrealistic 2000%+ total return and -99% MDD
            equity = (1.0 + strategy_trades["trade_return"]).cumprod()

        running_max = equity.cummax()
        drawdown = equity / running_max - 1.0
        total_return = float(equity.iloc[-1] - 1.0)
        span_days = max((end_date - start_date).days, 1)
        years = span_days / 365.25
        cagr = float((equity.iloc[-1] ** (1.0 / years) - 1.0) if years > 0 else total_return)
        win_rate = float((strategy_trades["trade_return"] > 0).mean())
        avg_return = float(strategy_trades["trade_return"].mean())
        benchmark_return = _compute_benchmark_return(
            prices_with_indicators=prices_with_indicators,
            benchmark_symbol=benchmark_symbol,
            start_date=start_date,
            end_date=end_date,
        )
        reports.append(
            {
                "strategy_id": strategy["strategy_id"],
                "strategy_name": strategy["name"],
                "trades": int(len(strategy_trades.index)),
                "win_rate": win_rate,
                "avg_trade_return": avg_return,
                "total_return": total_return,
                "cagr": cagr,
                "mdd": float(drawdown.min()),
                "turnover": float(len(strategy_trades.index) / max(years, 1.0)),
                "benchmark_symbol": benchmark_symbol,
                "benchmark_total_return": benchmark_return,
                "exit_reasons": strategy.get("backtest", {}).get(
                    "liquidity_rule"
                ),  # placeholder or actual
                "initial_capital": initial_capital,
                "final_balance": (
                    (initial_capital + strategy_trades["pnl_dollars"].sum())
                    if initial_capital is not None
                    else None
                ),
            }
        )

    return pd.DataFrame(reports), trade_frame


def save_backtest_results(
    reports: pd.DataFrame,
    trades: pd.DataFrame,
    output_dir: Path,
    start_date: date,
    end_date: date,
    initial_capital: Optional[float] = None,
) -> dict[str, Path]:
    output_path = output_dir / "backtests" / f"{start_date.isoformat()}_{end_date.isoformat()}"
    output_path.mkdir(parents=True, exist_ok=True)

    reports_path = output_path / "report.csv"
    trades_path = output_path / "trades.csv"
    report_md_path = output_path / "report.md"
    trades_md_path = output_path / "trades.md"
    metadata_path = output_path / "metadata.json"

    reports.to_csv(reports_path, index=False, encoding="utf-8")
    trades.to_csv(trades_path, index=False, encoding="utf-8")

    # Generate Report Markdown
    if not reports.empty:
        md_reports = reports.copy()
        md_reports = md_reports.rename(
            columns={
                "strategy_id": "策略 ID",
                "strategy_name": "策略名稱",
                "trades": "交易次數",
                "win_rate": "勝率",
                "avg_trade_return": "平均報酬",
                "total_return": "總報酬率",
                "cagr": "年化報酬 (CAGR)",
                "mdd": "最大回撤 (MDD)",
                "turnover": "週轉率",
                "benchmark_total_return": "基準報酬",
            }
        )
        # Format percentages
        for col in [
            "勝率",
            "平均報酬",
            "總報酬率",
            "年化報酬 (CAGR)",
            "最大回撤 (MDD)",
            "基準報酬",
        ]:
            if col in md_reports.columns:
                md_reports[col] = md_reports[col].apply(
                    lambda x: f"{x:.2%}" if pd.notnull(x) else "N/A"
                )

        md_content = "# 回測績效報告\n\n"
        md_content += f"- 測試期間: {start_date} ~ {end_date}\n"
        md_content += f"- 執行時間: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"

        if initial_capital is not None:
            # Get the last strategy's capital info (assuming one strategy for now or same settings)
            # Better: take from the first row if multiple
            row = reports.iloc[0]
            f_cap = row.get("initial_capital")
            f_bal = row.get("final_balance")
            if f_cap is not None and f_bal is not None:
                net_pnl = f_bal - f_cap
                md_content += f"- **初始資金: ${f_cap:,.0f}**\n"
                md_content += f"- **最終餘額: ${f_bal:,.0f}**\n"
                md_content += f"- **核心盈虧: ${net_pnl:,.0f} ({net_pnl/f_cap:+.2%})**\n"

        md_content += "\n"
        md_content += md_reports[
            [
                "策略名稱",
                "交易次數",
                "勝率",
                "平均報酬",
                "總報酬率",
                "年化報酬 (CAGR)",
                "最大回撤 (MDD)",
            ]
        ].to_markdown(index=False)
        report_md_path.write_text(md_content, encoding="utf-8")
    else:
        report_md_path.write_text("# 回測績效報告\n\n無交易紀錄。", encoding="utf-8")

    # Generate Trades Markdown
    if not trades.empty:
        md_trades = trades.copy()
        market_map = {"TWSE": "上市", "TPEX": "上櫃"}
        md_trades["market"] = md_trades["market"].map(lambda x: market_map.get(x, x))
        md_trades = md_trades.rename(
            columns={
                "strategy_name": "策略",
                "symbol": "代號",
                "name": "名稱",
                "market": "市場",
                "entry_date": "進場日",
                "exit_date": "出場日",
                "entry_price": "進場價",
                "exit_price": "出場價",
                "trade_return": "報酬率",
                "balance": "餘額",
            }
        )
        md_trades["報酬率"] = md_trades["報酬率"].apply(lambda x: f"{x:.2%}")
        if "餘額" in md_trades.columns:
            md_trades["餘額"] = md_trades["餘額"].apply(
                lambda x: f"${x:,.0f}" if pd.notnull(x) else ""
            )

        md_content = "# 交易明細\n\n"
        md_content += f"- 總計交易: {len(md_trades)} 筆\n\n"
        display_cols = [
            "策略",
            "市場",
            "代號",
            "名稱",
            "進場日",
            "進場價",
            "出場日",
            "出場價",
            "報酬率",
        ]
        if "餘額" in md_trades.columns:
            display_cols.append("餘額")
        md_content += md_trades[display_cols].to_markdown(index=False)
        trades_md_path.write_text(md_content, encoding="utf-8")
    else:
        trades_md_path.write_text("# 交易明細\n\n無交易紀錄。", encoding="utf-8")

    metadata = {
        "generated_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "strategies": reports["strategy_id"].tolist() if not reports.empty else [],
        "trades": int(len(trades.index)),
    }
    metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    return {
        "report": reports_path,
        "trades": trades_path,
        "report_md": report_md_path,
        "trades_md": trades_md_path,
        "metadata": metadata_path,
    }


def _compute_benchmark_return(
    prices_with_indicators: pd.DataFrame,
    benchmark_symbol: Optional[str],
    start_date: date,
    end_date: date,
) -> Optional[float]:
    if not benchmark_symbol:
        return None

    benchmark = prices_with_indicators[prices_with_indicators["symbol"] == benchmark_symbol].copy()
    if benchmark.empty:
        return None

    benchmark["trading_date"] = pd.to_datetime(benchmark["trading_date"]).dt.date
    benchmark = benchmark[
        (benchmark["trading_date"] >= start_date) & (benchmark["trading_date"] <= end_date)
    ].sort_values("trading_date")
    if len(benchmark.index) < 2:
        return None

    first_close = float(benchmark.iloc[0]["close"])
    last_close = float(benchmark.iloc[-1]["close"])
    if not first_close:
        return None
    return (last_close / first_close) - 1.0
