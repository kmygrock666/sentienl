from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd
from sqlalchemy.engine import Engine

from sentinel.calendar import build_trading_calendar
from sentinel.completeness import build_run_completeness_summary
from sentinel.config import Settings
from sentinel.logging_utils import get_logger
from sentinel.official_calendar import fetch_official_trading_calendar
from sentinel.persistence import finish_job_run, persist_pipeline_results, start_job_run
from sentinel.pipeline import compute_indicators, fetch_prices, save_results, scan_strategy
from sentinel.quality import validate_daily_prices
from sentinel.services.enrichment import apply_institutional_enrichment
from sentinel.storage import load_price_dataset, save_price_dataset, upsert_prices

_logger = get_logger(__name__)


@dataclass(frozen=True)
class DailyScanReport:
    run_id: str
    scan_results: pd.DataFrame
    artifacts: Dict[str, Path]
    completeness: dict
    rows_fetched: int
    rows_quarantined: int
    rows_in_dataset: int


def run_daily_scan(
    *,
    settings: Settings,
    engine: Optional[Engine],
    start_date: date,
    end_date: date,
    trading_date: date,
    markets: List[str],
    dataset_path: Path,
    output_dir: Path,
    data_version: str,
    calendar_source_mode: str,
    price_source_mode: str,
    strategy_definitions: List[dict],
    stock_master: pd.DataFrame,
    skip_indicators: bool = False,
    skip_strategies: bool = False,
    direction: Optional[str] = None,
    market_start_dates: Optional[Dict[str, date]] = None,
) -> DailyScanReport:
    """每日資料同步＋指標計算＋策略掃描的完整管線。

    抓價 → 品質驗證（隔離無效列）→ 更新 dataset → 指標 → 法人 enrich →
    策略掃描 → 完整度統計 → 輸出 artifacts 與資料庫持久化，全程掛 job run 記錄。
    """
    run_id = uuid.uuid4().hex

    _logger.info(
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
            source_mode=calendar_source_mode,
        )
        existing_prices = load_price_dataset(dataset_path)
        fetched_prices = fetch_prices(
            start_date=start_date,
            end_date=end_date,
            markets=markets,
            settings=settings,
            official_trading_calendar=official_trading_calendar,
            price_source_mode=price_source_mode,
            existing_prices=existing_prices,
            market_start_dates=market_start_dates,
        )
        validation_result = validate_daily_prices(fetched_prices, reference_prices=existing_prices)
        valid_prices = validation_result.valid_prices
        invalid_prices = validation_result.invalid_prices
        if not invalid_prices.empty:
            _logger.warning(
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

        if skip_indicators:
            _logger.info("skipping_indicators_as_requested")
            enriched_prices = merged_prices.copy()
        else:
            # Limit historical data to 300 trading days per stock for indicator computation.
            # MA200 needs 200 days; 300 provides a safe buffer without processing all history.
            indicator_cutoff = pd.Timestamp(trading_date) - pd.Timedelta(days=420)
            indicator_prices = merged_prices[
                pd.to_datetime(merged_prices["trading_date"]) >= indicator_cutoff
            ]
            _logger.info(
                "indicator_lookback_trimmed",
                extra={"rows_full": len(merged_prices), "rows_trimmed": len(indicator_prices)},
            )
            enriched_prices = compute_indicators(
                indicator_prices,
                trading_date=trading_date,
                markets=markets,
                cache_dir=settings.resolved_indicator_cache_dir,
                calc_version=settings.indicator_calc_version,
            )

        # 法人買賣超 enrichment（資料庫有資料才會生效；失敗不阻斷掃描）
        if engine is not None and not enriched_prices.empty:
            enriched_prices = apply_institutional_enrichment(enriched_prices, engine)

        if skip_strategies:
            _logger.info("skipping_strategies_as_requested")
            scan_results = pd.DataFrame()  # Empty result
        else:
            scan_results = scan_strategy(
                enriched_prices, trading_date=trading_date, strategies=strategy_definitions
            )
            if direction:
                scan_results = scan_results[scan_results["direction"] == direction].copy()

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

        _logger.info(
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

        return DailyScanReport(
            run_id=run_id,
            scan_results=scan_results,
            artifacts=artifacts,
            completeness=completeness_summary,
            rows_fetched=int(len(fetched_prices.index)),
            rows_quarantined=int(len(invalid_prices.index)),
            rows_in_dataset=int(len(merged_prices.index)),
        )
    except Exception as exc:
        if engine:
            finish_job_run(
                engine=engine,
                run_id=run_id,
                status="failed",
                error_summary=str(exc)[:1000],
            )
        _logger.error("pipeline_failed", extra={"run_id": run_id, "error": str(exc)})
        raise
