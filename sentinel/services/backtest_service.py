from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from sentinel.backtest.daily import run_backtest, save_backtest_results
from sentinel.backtest.minute import run_minute_backtest, save_minute_backtest_results
from sentinel.logging_utils import get_logger
from sentinel.services.pipeline import compute_indicators
from sentinel.storage import load_price_dataset
from sentinel.storage.persistence import finish_job_run, start_job_run

_logger = get_logger(__name__)


class SymbolNotInDatasetError(Exception):
    """--symbol 過濾後資料集為空。"""

    def __init__(self, symbol: str) -> None:
        super().__init__(f"No data found for symbol: {symbol} in the dataset.")
        self.symbol = symbol


@dataclass(frozen=True)
class BacktestJobReport:
    run_id: str
    reports: pd.DataFrame
    trades: pd.DataFrame
    artifacts: Dict[str, Path]


def run_backtest_job(
    *,
    engine: Optional[Engine],
    intraday_engine: Optional[Engine],
    start_date: date,
    end_date: date,
    markets: List[str],
    dataset_path: Path,
    output_dir: Path,
    strategy_definitions: List[dict],
    execution_model: str = "daily",
    strategy_mode: str = "standard",
    benchmark_symbol: Optional[str] = None,
    symbol: Optional[str] = None,
    initial_capital: Optional[float] = None,
    position_size: float = 100000,
) -> BacktestJobReport:
    """以本地價格 dataset 執行回測（daily 或 minute_bar 模型），輸出 artifacts。

    minute_bar 模型需要呼叫端提供 engine 與 intraday_engine。
    """
    run_id = uuid.uuid4().hex

    if engine:
        start_job_run(engine=engine, run_id=run_id, job_name="backtest")

    try:
        prices = load_price_dataset(dataset_path)
        resolved_markets = (
            markets or sorted(prices["market"].dropna().unique().tolist())
            if not prices.empty
            else ["TWSE"]
        )
        if not prices.empty:
            prices = prices[prices["market"].isin(resolved_markets)].copy()
        enriched_prices = compute_indicators(prices)

        if symbol:
            enriched_prices = enriched_prices[enriched_prices["symbol"] == symbol].copy()
            if enriched_prices.empty:
                raise SymbolNotInDatasetError(symbol)
            _logger.info(
                "backtest_symbol_filtered",
                extra={"symbol": symbol, "rows": int(len(enriched_prices.index))},
            )

        if execution_model == "minute_bar":
            with (
                Session(engine) as bt_session,
                Session(intraday_engine) as intraday_session,
            ):
                reports, trades = run_minute_backtest(
                    prices_with_indicators=enriched_prices,
                    strategies=strategy_definitions,
                    start_date=start_date,
                    end_date=end_date,
                    daily_session=bt_session,
                    intraday_session=intraday_session,
                    benchmark_symbol=benchmark_symbol,
                    strategy_mode=strategy_mode,
                    initial_capital=initial_capital,
                    position_size=position_size,
                )
            artifacts = save_minute_backtest_results(
                reports=reports,
                trades=trades,
                output_dir=output_dir,
                start_date=start_date,
                end_date=end_date,
                initial_capital=initial_capital,
            )
        else:
            reports, trades = run_backtest(
                prices_with_indicators=enriched_prices,
                strategies=strategy_definitions,
                start_date=start_date,
                end_date=end_date,
                benchmark_symbol=benchmark_symbol,
                initial_capital=initial_capital,
                position_size=position_size,
            )
            artifacts = save_backtest_results(
                reports=reports,
                trades=trades,
                output_dir=output_dir,
                start_date=start_date,
                end_date=end_date,
                initial_capital=initial_capital,
            )

        if engine:
            finish_job_run(
                engine=engine,
                run_id=run_id,
                status="success",
                rows_in=int(len(prices.index)),
                rows_out=int(len(trades.index)),
            )

        _logger.info(
            "backtest_finished",
            extra={
                "run_id": run_id,
                "markets": resolved_markets,
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

        return BacktestJobReport(run_id=run_id, reports=reports, trades=trades, artifacts=artifacts)
    except SymbolNotInDatasetError:
        raise
    except Exception as exc:
        if engine:
            finish_job_run(
                engine=engine,
                run_id=run_id,
                status="failed",
                error_summary=str(exc)[:1000],
            )
        _logger.error("backtest_failed", extra={"run_id": run_id, "error": str(exc)})
        raise
