from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

import pandas as pd

from sentinel.calendar import filter_trading_dates
from sentinel.config import Settings
from sentinel.indicator_cache import load_indicator_cache, save_indicator_cache
from sentinel.indicators import compute_3d_indicator_frame, compute_indicator_frame
from sentinel.logging_utils import get_logger
from sentinel.providers import SOURCE_MODE_AUTO, build_price_provider, normalize_market_name
from sentinel.strategies import DEFAULT_STRATEGY_DEFINITIONS, scan_strategies
from sentinel.utils import daterange

logger = get_logger(__name__)

PRICE_COLUMNS = [
    "symbol",
    "name",
    "market",
    "trading_date",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "turnover",
    "source",
]


def fetch_prices(
    start_date: date,
    end_date: date,
    markets: Iterable[str],
    settings: Settings,
    official_trading_calendar: Optional[pd.DataFrame] = None,
    price_source_mode: str = SOURCE_MODE_AUTO,
    existing_prices: Optional[pd.DataFrame] = None,
    market_start_dates: Optional[Dict[str, date]] = None,
    consecutive_empty_limit: int = 5,
) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []

    # Prepare historical check set for performance
    existing_keys = set()
    if existing_prices is not None and not existing_prices.empty:
        # Use (market, trading_date) tuples for checking
        # trading_date should already be normalized to date object in load_price_dataset
        existing_keys = set(
            zip(existing_prices["market"], pd.to_datetime(existing_prices["trading_date"]).dt.date)
        )

    for market_name in markets:
        normalized_market = normalize_market_name(market_name)
        provider = build_price_provider(normalized_market)
        # Per-market start date: allows each market to sync from its own latest date
        market_start = (market_start_dates or {}).get(normalized_market, start_date)
        trading_dates = filter_trading_dates(
            exchange=normalized_market,
            start_date=market_start,
            end_date=end_date,
            official_overrides=official_trading_calendar,
        )
        consecutive_empty = 0
        for trading_date in daterange(market_start, end_date):
            if trading_date not in trading_dates:
                logger.info(
                    "skip_non_trading_day",
                    extra={
                        "market": normalized_market,
                        "trading_date": trading_date.isoformat(),
                        "reason": "calendar",
                    },
                )
                continue

            # Local-first check: Skip network if data exists
            if (
                normalized_market,
                trading_date,
            ) in existing_keys and price_source_mode != "network":
                logger.info(
                    "skipping_fetch_local_data_exists",
                    extra={"market": normalized_market, "trading_date": trading_date.isoformat()},
                )
                # We need the actual data from existing_prices, but here we just return empty
                # and relying on the final merge. Actually, it's better to extract it here
                # to maintain the frames list integrity for this specific range.
                local_data = existing_prices[
                    (existing_prices["market"] == normalized_market)
                    & (pd.to_datetime(existing_prices["trading_date"]).dt.date == trading_date)
                ]
                if not local_data.empty:
                    frames.append(local_data)
                    consecutive_empty = 0
                    continue

            daily_prices = provider.fetch_day(
                trading_date=trading_date,
                settings=settings,
                source_mode=price_source_mode,
            )
            if daily_prices.empty:
                consecutive_empty += 1
                logger.info(
                    "empty_market_day",
                    extra={"market": normalized_market, "trading_date": trading_date.isoformat()},
                )
                if consecutive_empty >= consecutive_empty_limit:
                    logger.warning(
                        "market_fetch_stopped_consecutive_empty",
                        extra={
                            "market": normalized_market,
                            "stopped_at": trading_date.isoformat(),
                            "consecutive_empty": consecutive_empty,
                        },
                    )
                    break
                continue
            consecutive_empty = 0
            frames.append(daily_prices)

    if not frames:
        return pd.DataFrame(columns=PRICE_COLUMNS)

    merged = pd.concat(frames, ignore_index=True)
    merged["trading_date"] = pd.to_datetime(merged["trading_date"]).dt.date
    merged = merged.drop_duplicates(subset=["symbol", "trading_date", "market"], keep="last")
    merged = merged.sort_values(["market", "symbol", "trading_date"]).reset_index(drop=True)
    return merged[PRICE_COLUMNS]


def compute_indicators(
    prices: pd.DataFrame,
    trading_date: Optional[date] = None,
    markets: Optional[List[str]] = None,
    cache_dir: Optional[Path] = None,
    calc_version: str = "v1",
) -> pd.DataFrame:
    use_cache = bool(trading_date and markets and cache_dir)
    if use_cache:
        cached = load_indicator_cache(cache_dir, trading_date, markets, calc_version)
        if cached is not None:
            return cached

    result = compute_indicator_frame(prices)

    # Join 3D timeframe MAs (one value per symbol, propagated to all daily rows)
    indicators_3d = compute_3d_indicator_frame(prices)
    if not indicators_3d.empty:
        result = result.merge(indicators_3d, on=["market", "symbol"], how="left")

    if use_cache:
        save_indicator_cache(result, cache_dir, trading_date, markets, calc_version)
    return result


def scan_strategy(
    prices_with_indicators: pd.DataFrame,
    trading_date: date,
    strategies: Optional[Iterable[dict]] = None,
) -> pd.DataFrame:
    active_strategies = list(strategies) if strategies is not None else DEFAULT_STRATEGY_DEFINITIONS

    # We NO LONGER filter the entire dataset here because it breaks time-series continuity!
    # Filtering for 'is_pure_stock' and 'is_stuck_data' is now handled inside scan_strategies
    # for candidate rows on the specific trading_date.

    result = scan_strategies(
        prices_with_indicators, trading_date=trading_date, strategies=active_strategies
    )
    if result.empty:
        logger.warning("no_signals_found", extra={"trading_date": trading_date.isoformat()})
    return result


def save_results(
    scan_results: pd.DataFrame,
    output_dir: Path,
    run_id: str,
    trading_date: date,
    data_version: str,
    extra_metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Path]:
    output_path = output_dir / trading_date.isoformat()
    output_path.mkdir(parents=True, exist_ok=True)

    metadata = {
        "run_id": run_id,
        "trading_date": trading_date.isoformat(),
        "data_version": data_version,
        "generated_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "rows": int(len(scan_results.index)),
    }
    if extra_metadata:
        metadata.update(extra_metadata)

    csv_path = output_path / "scan_results.csv"
    json_path = output_path / "scan_results.json"
    markdown_path = output_path / "scan_results.md"
    metadata_path = output_path / "metadata.json"
    tradingview_path = output_path / f"tradingview_{trading_date.isoformat()}.txt"

    export_frame = scan_results.copy()
    if "trading_date" in export_frame.columns:
        export_frame["trading_date"] = pd.to_datetime(export_frame["trading_date"]).dt.strftime(
            "%Y-%m-%d"
        )
    export_frame["run_id"] = run_id
    export_frame["data_version"] = data_version
    export_frame.to_csv(csv_path, index=False, encoding="utf-8")

    # Generate TradingView Watchlist (Unique Tickers)
    if not scan_results.empty:
        # Format: MARKET:SYMBOL
        tv_tickers = scan_results.apply(lambda x: f"{x['market']}:{x['symbol']}", axis=1).unique()
        tradingview_path.write_text("\n".join(tv_tickers), encoding="utf-8")
    else:
        tradingview_path.write_text("", encoding="utf-8")

    # Sort and Generate Markdown Table
    if not scan_results.empty:
        md_df = scan_results.copy()

        # Sort by Strategy Name (A-Z), Industry (A-Z) and Close (Descending)
        sort_cols = []
        if "strategy_name" in md_df.columns:
            sort_cols.append("strategy_name")
        if "industry" in md_df.columns:
            sort_cols.append("industry")
        if "close" in md_df.columns:
            sort_cols.append("close")

        if sort_cols:
            ascending = [True] * len(sort_cols)
            if "close" in sort_cols:
                ascending[sort_cols.index("close")] = False
            md_df = md_df.sort_values(by=sort_cols, ascending=ascending)

        md_df = md_df.rename(
            columns={
                "trading_date": "日期",
                "strategy_name": "策略",
                "direction": "方向",
                "market": "市場",
                "symbol": "代號",
                "name": "名稱",
                "industry": "產業",
                "close": "收盤價",
                "ma20": "20MA",
                "prev_close": "前日收盤",
                "score": "符合度",
            }
        )
        if "市場" in md_df.columns:
            md_df["市場"] = (
                md_df["市場"].map({"TWSE": "上市", "TPEX": "上櫃"}).fillna(md_df["市場"])
            )
        if "方向" in md_df.columns:
            md_df["方向"] = (
                md_df["方向"].map({"long": "做多", "short": "做空"}).fillna(md_df["方向"])
            )

        if "符合度" in md_df.columns:
            md_df["符合度"] = pd.to_numeric(md_df["符合度"], errors="coerce").apply(
                lambda x: f"{x:.0%}" if pd.notna(x) else ""
            )

        # Format price columns to 2 decimal places for clarity
        for col in ["收盤價", "20MA", "前日收盤"]:
            if col in md_df.columns:
                md_df[col] = pd.to_numeric(md_df[col], errors="coerce").apply(
                    lambda x: f"{x:.2f}" if pd.notna(x) else ""
                )

        # Format table
        md_content = f"# 策略掃描結果 - {trading_date}\n\n"
        md_content += f"- 執行 ID: `{run_id}`\n"
        md_content += f"- 資料版本: `{data_version}`\n"
        md_content += f"- 總計符合: {len(md_df)} 筆\n\n"

        disp_cols = ["日期", "策略", "市場", "代號", "名稱", "前日收盤", "20MA", "收盤價", "符合度"]
        # Ensure all columns exist to avoid KeyError
        actual_cols = [col for col in disp_cols if col in md_df.columns]
        md_content += md_df[actual_cols].to_markdown(index=False)
        markdown_path.write_text(md_content, encoding="utf-8")
    else:
        markdown_path.write_text(
            f"# 策略掃描結果 - {trading_date}\n\n本次掃描無符合條件的標的。", encoding="utf-8"
        )

    payload = {
        "metadata": metadata,
        "results": [_json_safe(item) for item in export_frame.to_dict(orient="records")],
    }
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")

    return {
        "csv": csv_path,
        "json": json_path,
        "md": markdown_path,
        "metadata": metadata_path,
        "tradingview": tradingview_path,
    }


def _json_safe(value):
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if pd.isna(value):
        return None
    if isinstance(value, (pd.Timestamp, datetime, date)):
        return value.isoformat()
    if hasattr(value, "item"):
        try:
            return value.item()
        except Exception:
            pass
    return value
