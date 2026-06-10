from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

import pandas as pd
from sqlalchemy.orm import Session

from sentinel.logging_utils import get_logger
from sentinel.minute_bars import (
    calc_5day_ma,
    calc_intraday_avg,
    get_prev_close,
    is_limit_up_at_open,
    load_5min_bars,
)
from sentinel.strategies import scan_strategies

logger = get_logger(__name__)

# 台股漲停幅度
LIMIT_UP_PCT = 0.10
# 停利目標
DEFAULT_TAKE_PROFIT_PCT = 0.03
# 最大持有天數（安全閥，避免無限持有）
MAX_HOLDING_DAYS = 60
# 預先載入資料的天數緩衝
DATA_BUFFER_DAYS = 15


def run_minute_backtest(
    prices_with_indicators: pd.DataFrame,
    strategies: Iterable[dict],
    start_date: date,
    end_date: date,
    daily_session: Session,
    intraday_session: Session,
    benchmark_symbol: Optional[str] = None,
    strategy_mode: str = "standard",
    initial_capital: Optional[float] = None,
    position_size: float = 100000,
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """使用分鐘 K 線的精確回測引擎。

    進場：五分K五日均線價格
    出場：+3% 停利 / 跌破日均線停損 / 開盤>3%追漲停

    Args:
        prices_with_indicators: 含技術指標的日線 DataFrame（用於策略掃描產生訊號）。
        strategies: 策略定義列表。
        start_date: 回測起始日。
        end_date: 回測結束日。
        session: DB Session（用於查詢分鐘 K 線）。
        benchmark_symbol: 基準指標代碼。
        strategy_mode: "standard" 或 "tomorrow_star"（動態產生歷史盤中訊號）。

    Returns:
        (reports, trades) 兩個 DataFrame。
    """
    if strategy_mode == "tomorrow_star":
        from sentinel.intraday.historical_signals import generate_tomorrow_star_signals

        logger.info(
            "generate_historical_signals",
            extra={
                "mode": "tomorrow_star",
                "start_date": str(start_date),
                "end_date": str(end_date),
            },
        )
        signal_frame = generate_tomorrow_star_signals(
            daily_session, intraday_session, start_date, end_date
        )
        if signal_frame.empty:
            return pd.DataFrame(), pd.DataFrame()

        # 只保留 tomorrow_star 策略設定
        strategies = [s for s in strategies if s.get("strategy_id") == "tomorrow_star"]
        if not strategies:
            logger.error("missing_strategy_definition", extra={"strategy_id": "tomorrow_star"})
            return pd.DataFrame(), pd.DataFrame()
    else:
        full_frame = prices_with_indicators.copy()
        if full_frame.empty:
            return pd.DataFrame(), pd.DataFrame()

        full_frame["trading_date"] = pd.to_datetime(full_frame["trading_date"]).dt.date
        evaluation_frame = full_frame[
            (full_frame["trading_date"] >= start_date) & (full_frame["trading_date"] <= end_date)
        ].copy()
        if evaluation_frame.empty:
            return pd.DataFrame(), pd.DataFrame()

        # 產生每日訊號
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

        # 逐訊號模擬交易（取得所有候選交易）
        candidates: List[dict] = []
        for signal in strategy_signals.to_dict(orient="records"):
            trade = _simulate_single_trade(
                daily_session=daily_session,
                intraday_session=intraday_session,
                signal=signal,
                strategy=strategy,
                take_profit_pct=take_profit_pct,
                limit_up_pct=limit_up_pct,
                end_date=end_date,
            )
            if trade is not None:
                candidates.append(trade)

        # 套用資金限制邏輯
        if initial_capital is not None:
            candidates.sort(key=lambda x: (x["entry_date"], x["symbol"]))
            balance = initial_capital
            active_trades = []
            final_trades = []

            # 取得回測區間內所有交易日
            all_dates = sorted(signal_frame["trading_date"].unique())
            for d in all_dates:
                if isinstance(d, str):
                    d = date.fromisoformat(d)

                # 1. 處理今日出場
                still_active = []
                for t in active_trades:
                    if t["exit_date"] <= d:
                        balance += position_size * (1.0 + t["trade_return"])
                        t["balance"] = balance
                        final_trades.append(t)
                    else:
                        still_active.append(t)
                active_trades = still_active

                # 2. 處理今日進場
                todays_signals = [c for c in candidates if c["entry_date"] == d]
                for s in todays_signals:
                    if balance >= position_size:
                        balance -= position_size
                        active_trades.append(s)

            final_trades.extend(active_trades)  # 包含期末未平倉
            trades.extend(final_trades)
        else:
            trades.extend(candidates)

    trade_frame = pd.DataFrame(trades)
    if trade_frame.empty:
        return pd.DataFrame(), pd.DataFrame()

    # 產生策略績效報告
    reports = _build_strategy_reports(
        trade_frame=trade_frame,
        strategies=strategies,
        start_date=start_date,
        end_date=end_date,
        prices_with_indicators=prices_with_indicators,
        benchmark_symbol=benchmark_symbol,
        initial_capital=initial_capital,
        position_size=position_size,
    )
    return pd.DataFrame(reports), trade_frame


def _simulate_single_trade(
    daily_session: Session,
    intraday_session: Session,
    signal: dict,
    strategy: dict,
    take_profit_pct: float,
    limit_up_pct: float,
    end_date: date,
) -> Optional[dict]:
    """模擬單筆交易的完整進出場流程。"""
    market = signal["market"]
    symbol = signal["symbol"]
    signal_date = signal["trading_date"]
    if isinstance(signal_date, str):
        signal_date = date.fromisoformat(signal_date)

    # 進場日 = 訊號日隔日（需向後查詢實際交易日）
    entry_date_candidate = signal_date + timedelta(days=1)

    # 載入足夠的 5m 資料：訊號日前 DATA_BUFFER_DAYS 天到 end_date + 緩衝
    data_start = signal_date - timedelta(days=DATA_BUFFER_DAYS)
    data_end = min(end_date + timedelta(days=MAX_HOLDING_DAYS), end_date + timedelta(days=90))
    bars_5m = load_5min_bars(intraday_session, market, symbol, data_start, data_end)
    if bars_5m.empty:
        logger.debug(
            "no_minute_bars",
            extra={"symbol": symbol, "market": market, "signal_date": str(signal_date)},
        )
        return None

    # 找到進場日（訊號日之後第一個有資料的交易日）
    available_dates = sorted(bars_5m["trading_date"].unique())
    entry_dates = [d for d in available_dates if d > signal_date]
    if not entry_dates:
        return None
    entry_date = entry_dates[0]

    # 檢查漲停：取前一日收盤價
    prev_close = get_prev_close(daily_session, market, symbol, entry_date)
    if prev_close is None:
        # 備用：從 5m 資料取前一日最後一根 close
        prev_day_bars = bars_5m[bars_5m["trading_date"] < entry_date]
        if prev_day_bars.empty:
            return None
        prev_close = float(prev_day_bars.iloc[-1]["close"])

    if is_limit_up_at_open(bars_5m, entry_date, prev_close, limit_up_pct):
        logger.debug(
            "skip_limit_up",
            extra={"symbol": symbol, "entry_date": str(entry_date)},
        )
        return None

    # 計算進場價 = 五分K五日均線
    entry_price = calc_5day_ma(bars_5m, entry_date)
    if entry_price is None:
        return None

    # 模擬持有期間出場
    exit_result = _simulate_exit(
        bars_5m=bars_5m,
        entry_date=entry_date,
        entry_price=entry_price,
        take_profit_pct=take_profit_pct,
        limit_up_pct=limit_up_pct,
        prev_close=prev_close,
        max_holding_days=MAX_HOLDING_DAYS,
    )

    if exit_result is None:
        return None

    exit_date, exit_price, exit_reason = exit_result
    trade_return = (exit_price / entry_price) - 1.0 if entry_price else 0.0

    return {
        "strategy_id": strategy["strategy_id"],
        "strategy_name": strategy["name"],
        "symbol": symbol,
        "name": signal.get("name", ""),
        "market": market,
        "signal_date": signal_date,
        "entry_date": entry_date,
        "exit_date": exit_date,
        "entry_price": round(entry_price, 2),
        "exit_price": round(exit_price, 2),
        "trade_return": trade_return,
        "exit_reason": exit_reason,
        "execution_model_version": "minute_bar_execution",
    }


def _simulate_exit(
    bars_5m: pd.DataFrame,
    entry_date: date,
    entry_price: float,
    take_profit_pct: float,
    limit_up_pct: float,
    prev_close: float,
    max_holding_days: int,
) -> Optional[Tuple[date, float, str]]:
    """在持有期間逐日逐根模擬出場。

    Returns:
        (exit_date, exit_price, exit_reason) 或 None（若無法出場）。
    """
    target_price = entry_price * (1.0 + take_profit_pct)

    # 取入場後的所有交易日
    holding_bars = bars_5m[bars_5m["trading_date"] >= entry_date].copy()
    if holding_bars.empty:
        return None

    holding_dates = sorted(holding_bars["trading_date"].unique())

    # 限制最大持有天數
    if len(holding_dates) > max_holding_days:
        holding_dates = holding_dates[:max_holding_days]

    # 追蹤前一日收盤（用於計算當日漲停價）
    current_prev_close = prev_close

    for holding_day in holding_dates:
        day_bars = holding_bars[holding_bars["trading_date"] == holding_day].copy()
        if day_bars.empty:
            continue

        day_bars = day_bars.sort_values("bar_time").reset_index(drop=True)
        open_price = float(day_bars.iloc[0]["open"])

        # 計算當日漲停價
        limit_up_price = current_prev_close * (1.0 + limit_up_pct)

        # 判斷開盤是否已超過停利目標
        gap_up_mode = open_price > target_price

        if gap_up_mode:
            # 開盤 > +3%：改為追漲停
            day_target = limit_up_price
        else:
            day_target = target_price

        # 逐根 5m K 走場
        cumulative_closes = []
        for idx, bar in day_bars.iterrows():
            bar_high = float(bar["high"])
            bar_close = float(bar["close"])
            bar_time = bar["bar_time"]
            cumulative_closes.append(bar_close)

            # 計算到目前為止的日均線
            intraday_avg = sum(cumulative_closes) / len(cumulative_closes)

            # 條件 1：觸碰目標價 → 賣出
            if bar_high >= day_target:
                if gap_up_mode:
                    return (holding_day, round(day_target, 2), "limit_up")
                else:
                    return (holding_day, round(day_target, 2), "take_profit")

            # 條件 2：跌破日均線 且 低於停利目標 → 停損
            if bar_close < intraday_avg and bar_close < target_price:
                return (holding_day, round(bar_close, 2), "below_daily_avg")

        # 當日結束，更新前一日收盤
        current_prev_close = float(day_bars.iloc[-1]["close"])

    # 超過最大持有天數，以最後一根收盤價強制出場
    last_bar = holding_bars.iloc[-1]
    return (last_bar["trading_date"], round(float(last_bar["close"]), 2), "max_holding")


def _build_strategy_reports(
    trade_frame: pd.DataFrame,
    strategies: Iterable[dict],
    start_date: date,
    end_date: date,
    prices_with_indicators: pd.DataFrame,
    benchmark_symbol: Optional[str],
    initial_capital: Optional[float] = None,
    position_size: float = 100000,
) -> List[dict]:
    """產生各策略的績效報告。"""
    reports = []
    for strategy in strategies:
        strategy_trades = trade_frame[trade_frame["strategy_id"] == strategy["strategy_id"]].copy()
        if strategy_trades.empty:
            continue

        strategy_trades = strategy_trades.sort_values(["exit_date", "symbol"]).reset_index(
            drop=True
        )

        # 計算權益曲線
        if initial_capital is not None:
            strategy_trades["pnl_dollars"] = strategy_trades["trade_return"] * position_size
            equity_absolute = initial_capital + strategy_trades["pnl_dollars"].cumsum()
            equity = equity_absolute / initial_capital
        else:
            equity = (1.0 + strategy_trades["trade_return"]).cumprod()

        running_max = equity.cummax()
        drawdown = equity / running_max - 1.0
        total_return = float(equity.iloc[-1] - 1.0)
        span_days = max((end_date - start_date).days, 1)
        years = span_days / 365.25
        cagr = float((equity.iloc[-1] ** (1.0 / years) - 1.0) if years > 0 else total_return)
        win_rate = float((strategy_trades["trade_return"] > 0).mean())
        avg_return = float(strategy_trades["trade_return"].mean())

        # 出場原因統計
        exit_reasons = strategy_trades["exit_reason"].value_counts().to_dict()

        benchmark_return = _compute_benchmark_return(
            prices_with_indicators, benchmark_symbol, start_date, end_date
        )

        reports.append(
            {
                "strategy_id": strategy["strategy_id"],
                "strategy_name": strategy["name"],
                "trades": int(len(strategy_trades)),
                "win_rate": win_rate,
                "avg_trade_return": avg_return,
                "total_return": total_return,
                "cagr": cagr,
                "mdd": float(drawdown.min()),
                "turnover": float(len(strategy_trades) / max(years, 1.0)),
                "benchmark_symbol": benchmark_symbol,
                "benchmark_total_return": benchmark_return,
                "execution_model_version": "minute_bar_execution",
                "exit_reasons": exit_reasons,
                "initial_capital": initial_capital,
                "final_balance": (
                    (initial_capital + strategy_trades["pnl_dollars"].sum())
                    if initial_capital is not None
                    else None
                ),
            }
        )
    return reports


def _compute_benchmark_return(
    prices_with_indicators: pd.DataFrame,
    benchmark_symbol: Optional[str],
    start_date: date,
    end_date: date,
) -> Optional[float]:
    """計算基準指數報酬。"""
    if not benchmark_symbol:
        return None
    benchmark = prices_with_indicators[prices_with_indicators["symbol"] == benchmark_symbol].copy()
    if benchmark.empty:
        return None
    benchmark["trading_date"] = pd.to_datetime(benchmark["trading_date"]).dt.date
    benchmark = benchmark[
        (benchmark["trading_date"] >= start_date) & (benchmark["trading_date"] <= end_date)
    ].sort_values("trading_date")
    if len(benchmark) < 2:
        return None
    first_close = float(benchmark.iloc[0]["close"])
    last_close = float(benchmark.iloc[-1]["close"])
    if not first_close:
        return None
    return (last_close / first_close) - 1.0


def save_minute_backtest_results(
    reports: pd.DataFrame,
    trades: pd.DataFrame,
    output_dir: Path,
    start_date: date,
    end_date: date,
    initial_capital: Optional[float] = None,
) -> dict[str, Path]:
    """儲存分鐘回測結果。"""
    output_path = (
        output_dir
        / "backtests"
        / "minute_{0}_{1}".format(start_date.isoformat(), end_date.isoformat())
    )
    output_path.mkdir(parents=True, exist_ok=True)

    reports_path = output_path / "report.csv"
    trades_path = output_path / "trades.csv"
    report_md_path = output_path / "report.md"
    trades_md_path = output_path / "trades.md"
    metadata_path = output_path / "metadata.json"

    reports.to_csv(reports_path, index=False, encoding="utf-8")
    trades.to_csv(trades_path, index=False, encoding="utf-8")

    # 產生 Markdown 報告
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

        md_content = f"# 分鐘K線精確回測 - 績效報告\n\n"
        md_content += f"- 測試期間: {start_date} ~ {end_date}\n"
        md_content += f"- 執行模型: `minute_bar_execution`\n"

        if initial_capital is not None:
            row = reports.iloc[0]
            f_cap = row.get("initial_capital")
            f_bal = row.get("final_balance")
            if f_cap is not None and f_bal is not None:
                net_pnl = f_bal - f_cap
                md_content += f"- **初始資金: ${f_cap:,.0f}**\n"
                md_content += f"- **最終餘額: ${f_bal:,.0f}**\n"
                md_content += f"- **核心盈虧: ${net_pnl:,.0f} ({net_pnl/f_cap:+.2%})**\n"

        md_content += f"- 進場: 五分K五日均線\n"
        md_content += f"- 出場: +3%停利 / 跌破日均線停損 / 開盤>3%追漲停\n"
        md_content += f"- 執行時間: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"

        display_cols = [
            "策略名稱",
            "交易次數",
            "勝率",
            "平均報酬",
            "總報酬率",
            "年化報酬 (CAGR)",
            "最大回撤 (MDD)",
        ]
        actual_cols = [c for c in display_cols if c in md_reports.columns]
        md_content += md_reports[actual_cols].to_markdown(index=False)

        # 出場原因統計
        if "exit_reasons" in reports.columns:
            md_content += "\n\n## 出場原因分佈\n\n"
            reason_labels = {
                "take_profit": "✅ 停利 (+3%)",
                "limit_up": "🚀 漲停賣出",
                "below_daily_avg": "❌ 跌破日均線",
                "max_holding": "⏰ 持有期滿",
            }
            for _, row in reports.iterrows():
                reasons = row.get("exit_reasons", {})
                if isinstance(reasons, str):
                    reasons = json.loads(reasons) if reasons else {}
                md_content += f"\n### {row['strategy_name']}\n\n"
                for reason_key, count in reasons.items():
                    label = reason_labels.get(reason_key, reason_key)
                    md_content += f"- {label}: {count} 筆\n"

        report_md_path.write_text(md_content, encoding="utf-8")
    else:
        report_md_path.write_text("# 分鐘K線精確回測 - 績效報告\n\n無交易紀錄。", encoding="utf-8")

    # 交易明細 Markdown
    if not trades.empty:
        md_trades = trades.copy()
        market_map = {"TWSE": "上市", "TPEX": "上櫃"}
        md_trades["market"] = md_trades["market"].map(lambda x: market_map.get(x, x))
        reason_labels = {
            "take_profit": "停利",
            "limit_up": "漲停",
            "below_daily_avg": "跌破日均",
            "max_holding": "期滿",
        }
        md_trades["exit_reason"] = md_trades["exit_reason"].map(lambda x: reason_labels.get(x, x))
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
                "exit_reason": "出場原因",
            }
        )
        md_trades["報酬率"] = md_trades["報酬率"].apply(lambda x: f"{x:.2%}")
        if "balance" in md_trades.columns:
            md_trades = md_trades.rename(columns={"balance": "餘額"})
            md_trades["餘額"] = md_trades["餘額"].apply(
                lambda x: f"${x:,.0f}" if pd.notnull(x) else ""
            )

        md_content = f"# 分鐘K線精確回測 - 交易明細\n\n"
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
            "出場原因",
        ]
        if "餘額" in md_trades.columns:
            display_cols.append("餘額")
        md_content += md_trades[display_cols].to_markdown(index=False)
        trades_md_path.write_text(md_content, encoding="utf-8")
    else:
        trades_md_path.write_text("# 分鐘K線精確回測 - 交易明細\n\n無交易紀錄。", encoding="utf-8")

    metadata = {
        "generated_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "execution_model": "minute_bar_execution",
        "strategies": reports["strategy_id"].tolist() if not reports.empty else [],
        "trades": int(len(trades)),
    }
    metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")

    return {
        "report": reports_path,
        "trades": trades_path,
        "report_md": report_md_path,
        "trades_md": trades_md_path,
        "metadata": metadata_path,
    }
