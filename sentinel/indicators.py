from __future__ import annotations

import os
from concurrent.futures import ProcessPoolExecutor
from typing import Dict, List

import numpy as np
import pandas as pd

pd.set_option("future.no_silent_downcasting", True)


INDICATOR_SPECS: Dict[str, Dict[str, object]] = {
    "ma5": {
        "indicator_name": "ma5",
        "params": {"window": 5, "source": "close"},
        "source_field": "adjusted_close",
    },
    "ma10": {
        "indicator_name": "ma10",
        "params": {"window": 10, "source": "close"},
        "source_field": "adjusted_close",
    },
    "ma15": {
        "indicator_name": "ma15",
        "params": {"window": 15, "source": "close"},
        "source_field": "adjusted_close",
    },
    "ma20": {
        "indicator_name": "ma20",
        "params": {"window": 20, "source": "close"},
        "source_field": "adjusted_close",
    },
    "ma30": {
        "indicator_name": "ma30",
        "params": {"window": 30, "source": "close"},
        "source_field": "adjusted_close",
    },
    "ma60": {
        "indicator_name": "ma60",
        "params": {"window": 60, "source": "close"},
        "source_field": "adjusted_close",
    },
    "ma200": {
        "indicator_name": "ma200",
        "params": {"window": 200, "source": "close"},
        "source_field": "adjusted_close",
    },
    "ma240": {
        "indicator_name": "ma240",
        "params": {"window": 240, "source": "close"},
        "source_field": "adjusted_close",
    },
    "ma5_up": {"indicator_name": "ma5_up", "params": {}, "source_field": "price_levels"},
    "ma10_up": {"indicator_name": "ma10_up", "params": {}, "source_field": "price_levels"},
    "ma15_up": {"indicator_name": "ma15_up", "params": {}, "source_field": "price_levels"},
    "ma20_up": {"indicator_name": "ma20_up", "params": {}, "source_field": "price_levels"},
    "ma30_up": {"indicator_name": "ma30_up", "params": {}, "source_field": "price_levels"},
    "ma60_up": {"indicator_name": "ma60_up", "params": {}, "source_field": "price_levels"},
    "volume_ma5": {
        "indicator_name": "volume_ma5",
        "params": {"window": 5, "source": "volume"},
        "source_field": "volume",
    },
    "rsi14": {
        "indicator_name": "rsi14",
        "params": {"window": 14, "source": "close"},
        "source_field": "adjusted_close",
    },
    "macd_line": {
        "indicator_name": "macd_line",
        "params": {"fast": 12, "slow": 26, "signal": 9, "source": "close"},
        "source_field": "adjusted_close",
    },
    "macd_signal": {
        "indicator_name": "macd_signal",
        "params": {"fast": 12, "slow": 26, "signal": 9, "source": "close"},
        "source_field": "adjusted_close",
    },
    "macd_hist": {
        "indicator_name": "macd_hist",
        "params": {"fast": 12, "slow": 26, "signal": 9, "source": "close"},
        "source_field": "adjusted_close",
    },
    "kd_k": {
        "indicator_name": "kd_k",
        "params": {"window": 9, "smooth": 3},
        "source_field": "high_low_close",
    },
    "kd_d": {
        "indicator_name": "kd_d",
        "params": {"window": 9, "smooth": 3},
        "source_field": "high_low_close",
    },
    "atr14": {
        "indicator_name": "atr14",
        "params": {"window": 14},
        "source_field": "high_low_close",
    },
    "bb_middle_20": {
        "indicator_name": "bb_middle_20",
        "params": {"window": 20, "stddev": 2, "source": "close"},
        "source_field": "adjusted_close",
    },
    "bb_upper_20": {
        "indicator_name": "bb_upper_20",
        "params": {"window": 20, "stddev": 2, "source": "close"},
        "source_field": "adjusted_close",
    },
    "bb_lower_20": {
        "indicator_name": "bb_lower_20",
        "params": {"window": 20, "stddev": 2, "source": "close"},
        "source_field": "adjusted_close",
    },
    "high_20": {
        "indicator_name": "high_20",
        "params": {"window": 20, "source": "high"},
        "source_field": "high",
    },
    "is_red_candle": {
        "indicator_name": "is_red_candle",
        "params": {},
        "source_field": "open_close",
    },
    "day_range_pos": {
        "indicator_name": "day_range_pos",
        "params": {},
        "source_field": "high_low_close",
    },
    "change_pct": {"indicator_name": "change_pct", "params": {}, "source_field": "adjusted_close"},
    "is_pure_stock": {"indicator_name": "is_pure_stock", "params": {}, "source_field": "symbol"},
    "open_47d_prev": {
        "indicator_name": "open_47d_prev",
        "params": {"window": 93, "source": "open"},
        "source_field": "open",
    },
    "high_47d_prev": {
        "indicator_name": "high_47d_prev",
        "params": {"window": 94, "source": "high"},
        "source_field": "high",
    },
    "has_breakout_47d": {
        "indicator_name": "has_breakout_47d",
        "params": {},
        "source_field": "price_levels",
    },
    "has_washout_47d": {
        "indicator_name": "has_washout_47d",
        "params": {},
        "source_field": "price_levels",
    },
    "ma20_cross_up": {
        "indicator_name": "ma20_cross_up",
        "params": {},
        "source_field": "price_levels",
    },
    "ma20_cross_up_3d": {
        "indicator_name": "ma20_cross_up_3d",
        "params": {},
        "source_field": "price_levels",
    },
    "ma10_cross_up": {
        "indicator_name": "ma10_cross_up",
        "params": {},
        "source_field": "price_levels",
    },
    "has_closed_below_ma10_20d": {
        "indicator_name": "has_closed_below_ma10_20d",
        "params": {},
        "source_field": "price_levels",
    },
    "ma10_1d_bullish": {
        "indicator_name": "ma10_1d_bullish",
        "params": {},
        "source_field": "price_levels",
    },
    "ma30_cross_up": {
        "indicator_name": "ma30_cross_up",
        "params": {},
        "source_field": "price_levels",
    },
    "has_closed_below_ma30_20d": {
        "indicator_name": "has_closed_below_ma30_20d",
        "params": {},
        "source_field": "price_levels",
    },
    "ma30_3d_bullish": {
        "indicator_name": "ma30_3d_bullish",
        "params": {},
        "source_field": "price_levels",
    },
    "is_stuck_data": {
        "indicator_name": "is_stuck_data",
        "params": {},
        "source_field": "close_volume",
    },
    "high_black_47d_prev": {
        "indicator_name": "high_black_47d_prev",
        "params": {"window": 47},
        "source_field": "ohlc",
    },
    "entity_high_black_47d_prev": {
        "indicator_name": "entity_high_black_47d_prev",
        "params": {"window": 47},
        "source_field": "ohlc",
    },
    "high_black_18d_prev": {
        "indicator_name": "high_black_18d_prev",
        "params": {"window": 18},
        "source_field": "ohlc",
    },
    "entity_high_black_18d_prev": {
        "indicator_name": "entity_high_black_18d_prev",
        "params": {"window": 18},
        "source_field": "ohlc",
    },
    "high_black_3d_prev": {
        "indicator_name": "high_black_3d_prev",
        "params": {"window": 3},
        "source_field": "ohlc",
    },
    "entity_high_black_3d_prev": {
        "indicator_name": "entity_high_black_3d_prev",
        "params": {"window": 3},
        "source_field": "ohlc",
    },
    "ma200_black_47d_prev": {
        "indicator_name": "ma200_black_47d_prev",
        "params": {"window": 47},
        "source_field": "ohlc",
    },
    "ma200_black_18d_prev": {
        "indicator_name": "ma200_black_18d_prev",
        "params": {"window": 18},
        "source_field": "ohlc",
    },
    "ma200_black_3d_prev": {
        "indicator_name": "ma200_black_3d_prev",
        "params": {"window": 3},
        "source_field": "ohlc",
    },
    "entity_high": {"indicator_name": "entity_high", "params": {}, "source_field": "ohlc"},
    "entity_high_max_2d_prev": {
        "indicator_name": "entity_high_max_2d_prev",
        "params": {},
        "source_field": "ohlc",
    },
    "entity_high_max_2d_prev_prev_1": {
        "indicator_name": "entity_high_max_2d_prev_prev_1",
        "params": {},
        "source_field": "ohlc",
    },
    "close_prev_1": {
        "indicator_name": "close_prev_1",
        "params": {},
        "source_field": "adjusted_close",
    },
    "close_prev_2": {
        "indicator_name": "close_prev_2",
        "params": {},
        "source_field": "adjusted_close",
    },
    "close_prev_3": {
        "indicator_name": "close_prev_3",
        "params": {},
        "source_field": "adjusted_close",
    },
    "high_prev_1": {"indicator_name": "high_prev_1", "params": {}, "source_field": "high"},
    "high_max_2d": {"indicator_name": "high_max_2d", "params": {}, "source_field": "high"},
    "high_47d_prev_raw": {
        "indicator_name": "high_47d_prev_raw",
        "params": {},
        "source_field": "high",
    },
    "high_max_2d_raw": {"indicator_name": "high_max_2d_raw", "params": {}, "source_field": "high"},
    "entity_high_prev_1": {
        "indicator_name": "entity_high_prev_1",
        "params": {},
        "source_field": "ohlc",
    },
    "has_closed_below_ma20_20d": {
        "indicator_name": "has_closed_below_ma20_20d",
        "params": {},
        "source_field": "price_levels",
    },
    "close_47d_prev": {
        "indicator_name": "close_47d_prev",
        "params": {},
        "source_field": "adjusted_close",
    },
    "close_18d_prev": {
        "indicator_name": "close_18d_prev",
        "params": {},
        "source_field": "adjusted_close",
    },
    "high_47d_max": {
        "indicator_name": "high_47d_max",
        "params": {"window": 47, "source": "high"},
        "source_field": "high",
    },
    "ma600": {
        "indicator_name": "ma600",
        "params": {"window": 600, "source": "close"},
        "source_field": "adjusted_close",
    },
    "ma200_47d_prev": {
        "indicator_name": "ma200_47d_prev",
        "params": {},
        "source_field": "price_levels",
    },
    "ma200_18d_prev": {
        "indicator_name": "ma200_18d_prev",
        "params": {},
        "source_field": "price_levels",
    },
    "ma200_3d_prev": {
        "indicator_name": "ma200_3d_prev",
        "params": {},
        "source_field": "price_levels",
    },
    "raw_close": {"indicator_name": "raw_close", "params": {}, "source_field": "close"},
    "raw_close_prev_1": {
        "indicator_name": "raw_close_prev_1",
        "params": {},
        "source_field": "close",
    },
    "raw_close_prev_3": {
        "indicator_name": "raw_close_prev_3",
        "params": {},
        "source_field": "close",
    },
    "ma20_raw": {"indicator_name": "ma20_raw", "params": {"window": 20}, "source_field": "close"},
    "ma200_raw": {
        "indicator_name": "ma200_raw",
        "params": {"window": 200},
        "source_field": "close",
    },
    "ma20_raw_cross_up": {
        "indicator_name": "ma20_raw_cross_up",
        "params": {},
        "source_field": "price_levels",
    },
    "has_closed_below_ma20_raw_20d": {
        "indicator_name": "has_closed_below_ma20_raw_20d",
        "params": {},
        "source_field": "price_levels",
    },
    "high_max_2d_raw": {"indicator_name": "high_max_2d_raw", "params": {}, "source_field": "high"},
    "ma180": {
        "indicator_name": "ma180",
        "params": {"window": 180, "source": "close"},
        "source_field": "adjusted_close",
    },
    "ma360": {
        "indicator_name": "ma360",
        "params": {"window": 360, "source": "close"},
        "source_field": "adjusted_close",
    },
    "low_prev_1": {"indicator_name": "low_prev_1", "params": {}, "source_field": "low"},
    "adj_close": {"indicator_name": "adj_close", "params": {}, "source_field": "adjusted_close"},
    "adj_low": {"indicator_name": "adj_low", "params": {}, "source_field": "low"},
    "ma200_raw_3d_prev": {
        "indicator_name": "ma200_raw_3d_prev",
        "params": {},
        "source_field": "price_levels",
    },
    "volume_prev_1": {"indicator_name": "volume_prev_1", "params": {}, "source_field": "volume"},
    "volume_ma5_prev_1": {
        "indicator_name": "volume_ma5_prev_1",
        "params": {},
        "source_field": "volume",
    },
    "high_20_prev_1": {"indicator_name": "high_20_prev_1", "params": {}, "source_field": "high"},
    "upper_shadow_ratio": {
        "indicator_name": "upper_shadow_ratio",
        "params": {},
        "source_field": "ohlc",
    },
    "is_shooting_star": {
        "indicator_name": "is_shooting_star",
        "params": {},
        "source_field": "ohlc",
    },
    "is_shooting_star_prev_1": {
        "indicator_name": "is_shooting_star_prev_1",
        "params": {},
        "source_field": "ohlc",
    },
    "is_fairy_guide_black": {
        "indicator_name": "is_fairy_guide_black",
        "params": {},
        "source_field": "ohlc",
    },
    "prev_candle_body_mid": {
        "indicator_name": "prev_candle_body_mid",
        "params": {},
        "source_field": "ohlc",
    },
}


def _compute_chunk(groups: List[pd.DataFrame]) -> List[pd.DataFrame]:
    """Worker function: process a chunk of stock groups sequentially.
    Must be module-level for ProcessPoolExecutor pickling."""
    return [_compute_group_indicators(g) for g in groups]


def compute_indicator_frame(prices: pd.DataFrame) -> pd.DataFrame:
    if prices.empty:
        frame = prices.copy()
        for column in INDICATOR_SPECS:
            frame[column] = pd.Series(dtype=float)
        return frame

    frame = prices.copy()
    frame["trading_date"] = pd.to_datetime(frame["trading_date"])
    frame = frame.sort_values(["market", "symbol", "trading_date"]).reset_index(drop=True)

    groups = [g.copy() for _, g in frame.groupby(["market", "symbol"], sort=False)]

    n_workers = min(os.cpu_count() or 1, 8)
    chunk_size = max(1, len(groups) // n_workers)
    chunks = [groups[i : i + chunk_size] for i in range(0, len(groups), chunk_size)]

    with ProcessPoolExecutor(max_workers=n_workers) as executor:
        chunk_results = list(executor.map(_compute_chunk, chunks))

    enriched_groups = [g for chunk in chunk_results for g in chunk]
    enriched = pd.concat(enriched_groups, ignore_index=True)
    enriched["trading_date"] = enriched["trading_date"].dt.date
    return enriched


INDICATOR_SPECS_3D: Dict[str, str] = {
    "ma20_3d": "MA of last 20 3-day bars (≈ 60 trading days)",
    "ma60_3d": "MA of last 60 3-day bars (≈ 180 trading days)",
    "ma120_3d": "MA of last 120 3-day bars (≈ 360 trading days)",
}


def compute_3d_indicator_frame(prices: pd.DataFrame) -> pd.DataFrame:
    """Compute MA indicators on 3-day aggregated bars.

    Returns one row per (market, symbol) with the latest available 3D MA values.
    These columns should be joined onto the daily indicator frame by (market, symbol).
    """
    if prices.empty:
        return pd.DataFrame(columns=["market", "symbol"] + list(INDICATOR_SPECS_3D))

    prices = prices.copy()
    prices["trading_date"] = pd.to_datetime(prices["trading_date"]).dt.date

    results: List[Dict] = []
    for (market, symbol), group in prices.groupby(["market", "symbol"]):
        group = group.sort_values("trading_date").reset_index(drop=True)

        # Assign 3-day period index by row position (each trading day counts once)
        group["period_idx"] = group.index // 3

        # Only keep complete 3-day blocks
        period_counts = group.groupby("period_idx").size()
        complete = period_counts[period_counts == 3].index
        if len(complete) == 0:
            continue

        agg = (
            group[group["period_idx"].isin(complete)]
            .groupby("period_idx")
            .agg(close=("close", "last"))
            .reset_index()
        )
        close_3d = pd.to_numeric(agg["close"], errors="coerce")

        row: Dict = {"market": market, "symbol": symbol}
        for window, col in [(20, "ma20_3d"), (60, "ma60_3d"), (120, "ma120_3d")]:
            series = close_3d.rolling(window=window, min_periods=window).mean()
            row[col] = float(series.iloc[-1]) if pd.notna(series.iloc[-1]) else None
        results.append(row)

    if not results:
        return pd.DataFrame(columns=["market", "symbol"] + list(INDICATOR_SPECS_3D))
    return pd.DataFrame(results)


def _resolve_price_series(group: pd.DataFrame) -> Dict[str, pd.Series]:
    """還原調整後 OHLC 與原始收盤。"""
    raw_close = pd.to_numeric(group["close"], errors="coerce")
    adj_close_col = group.get("adjusted_close")

    # Handle adjusted prices: prioritize adjusted_close if it exists and has valid data
    if adj_close_col is not None and adj_close_col.notna().any():
        close = pd.to_numeric(adj_close_col, errors="coerce")
        # Estimate adjustment factor to align OHLC with adjusted close
        # factor = adjusted_close / raw_close
        # handle zero division by using 1.0
        safe_raw_close = raw_close.replace(0, pd.NA)
        adj_factor = (close / safe_raw_close).fillna(1.0)

        open_p = pd.to_numeric(group["open"], errors="coerce") * adj_factor
        high = pd.to_numeric(group["high"], errors="coerce") * adj_factor
        low = pd.to_numeric(group["low"], errors="coerce") * adj_factor
    else:
        close = raw_close
        open_p = pd.to_numeric(group["open"], errors="coerce")
        high = pd.to_numeric(group["high"], errors="coerce")
        low = pd.to_numeric(group["low"], errors="coerce")

    volume = pd.to_numeric(group["volume"], errors="coerce")
    return {
        "close": close,
        "open_p": open_p,
        "high": high,
        "low": low,
        "raw_close": raw_close,
        "volume": volume,
    }


def _add_moving_average_indicators(
    group: pd.DataFrame, close: pd.Series, volume: pd.Series
) -> None:
    """均線、均線方向、量均。"""
    for window in (5, 10, 15, 20, 30, 60, 180, 200, 360, 600):
        group["ma{0}".format(window)] = close.rolling(window=window, min_periods=window).mean()

    for window in (5, 10, 15, 20, 30, 60):
        group["ma{0}_up".format(window)] = (
            group["ma{0}".format(window)] > group["ma{0}".format(window)].shift(1)
        ).astype(float)

    group["volume_ma5"] = volume.rolling(window=5, min_periods=5).mean()


def _add_oscillator_indicators(
    group: pd.DataFrame, close: pd.Series, open_p: pd.Series, high: pd.Series, low: pd.Series
) -> None:
    """RSI、MACD、KD、ATR、布林、high_20、紅K、日內位置、漲跌幅。"""
    group["rsi14"] = _compute_rsi(close, window=14)

    macd_line, macd_signal, macd_hist = _compute_macd(close)
    group["macd_line"] = macd_line
    group["macd_signal"] = macd_signal
    group["macd_hist"] = macd_hist

    kd_k, kd_d = _compute_kd(high=high, low=low, close=close)
    group["kd_k"] = kd_k
    group["kd_d"] = kd_d

    group["atr14"] = _compute_atr(high=high, low=low, close=close, window=14)

    bb_middle, bb_upper, bb_lower = _compute_bollinger_bands(close=close, window=20, stddev=2.0)
    group["bb_middle_20"] = bb_middle
    group["bb_upper_20"] = bb_upper
    group["bb_lower_20"] = bb_lower

    # New indicators for "純價漲高量趨創"
    group["high_20"] = high.rolling(window=20, min_periods=20).max()
    group["is_red_candle"] = (close > open_p).astype(float)
    denom = (high - low).replace(0.0, pd.NA)
    group["day_range_pos"] = ((close - low) / denom).fillna(0.0)
    group["change_pct"] = close.pct_change() * 100.0


def _add_purity_and_blackcandle_indicators(
    group: pd.DataFrame, close: pd.Series, open_p: pd.Series, high: pd.Series
) -> None:
    """47D 參考欄、is_pure_stock 判定、黑K多週期欄位。"""
    # New indicators for 47-Day K-line strategy
    # "前一根 47天 K線" means the 47-day block before the current 47-day block.
    # Therefore, the open of that block is the open price 93 days ago (shift 93),
    # and the high of that block is the rolling max of 47 days, shifted by 47 days.
    group["open_47d_prev"] = open_p.shift(93)
    group["high_47d_prev"] = high.rolling(window=47, min_periods=47).max().shift(47)

    # Refined is_pure_stock logic for Taiwan market:
    symbol_str = str(group["symbol"].iloc[0]).strip()
    is_pure = 1.0

    # 1. Length-based filtering:
    # Regular stocks are 4 digits. Warrants and some ETFs are 5-6 digits.
    if len(symbol_str) > 4:
        is_pure = 0.0
    # 2. Suffix-based filtering for Preferred Stocks or special classes:
    # 4-digit codes ending in A, B, C, D, E, F, G are usually preferred stocks.
    elif any(symbol_str.endswith(suffix) for suffix in ["A", "B", "C", "D", "E", "F", "G"]):
        is_pure = 0.0
    # 3. ETF Prefix checking:
    # In Taiwan, many ETFs start with '00' (even 4-digit ones like 0050).
    # Since we want "Pure Stocks" (non-ETF), we exclude these.
    elif symbol_str.startswith("00"):
        is_pure = 0.0

    group["is_pure_stock"] = is_pure

    # --- Black Candle (Bearish) Multi-Period Metrics ---
    # Definitions:
    #   Black Candle = Close < Open
    #   Entity High = max(Open, Close) -> for Black, this is Open
    # We need the most recent black candle in the *previous* N-day block.
    # Logic:
    # 1. Identify all black candles
    # 2. Get their High and Open (Entity High)
    # 3. For each date, find the most recent one that *ended* before the block started (shifted by window).
    # Simplified approach: If the user says "47D", they likely mean the 47-day window trailing from today's perspective.
    # "前一根黑K棒" usually means the most recent bearish candle.

    is_black = close < open_p
    black_high = high.where(is_black)
    black_open = open_p.where(is_black)
    black_ma200 = group["ma200"].where(is_black)

    # ffill().shift(1) 各計算一次，三個 window 共用同一結果（語意相同）
    _bh_prev = black_high.ffill().shift(1)
    _bo_prev = black_open.ffill().shift(1)
    _bm_prev = black_ma200.ffill().shift(1)
    for w in [47, 18, 3]:
        group[f"high_black_{w}d_prev"] = _bh_prev
        group[f"entity_high_black_{w}d_prev"] = _bo_prev
        group[f"ma200_black_{w}d_prev"] = _bm_prev


def _add_washout_recovery_indicators(
    group: pd.DataFrame, close: pd.Series, high: pd.Series, low: pd.Series, volume: pd.Series
) -> None:
    """47D 洗盤回升、ma10/ma20/ma30 站回系列、prev_close/prev_ma20、is_stuck_data。"""
    # --- Stateful Sequential Indicators for 47-Day Washout Recovery ---
    # 1. has_breakout_47d: 1 iff price reached 'high_47d_prev' in last 120 days
    is_at_breakout = (high >= group["high_47d_prev"]).astype(float)
    group["has_breakout_47d"] = is_at_breakout.rolling(window=120, min_periods=1).max().fillna(0.0)

    # 2. has_washout_47d: 1 iff dropped below ma20 while having 'has_breakout_47d' active in the window
    # Logic: Look for any instance in the last 60 days where (has_breakout_47d was true AND low < ma20)
    was_below_ma20 = (low < group["ma20"]).astype(float)
    washout_signal = ((group["has_breakout_47d"] > 0) & (was_below_ma20 > 0)).astype(float)
    group["has_washout_47d"] = washout_signal.rolling(window=60, min_periods=1).max().fillna(0.0)

    # 3. ma20_cross_up: Cross above MA20 on the current bar
    cp_close = close.shift(1)
    cp_ma20 = group["ma20"].shift(1)
    group["ma20_cross_up"] = ((cp_close <= cp_ma20) & (close > group["ma20"])).astype(float)
    group["ma20_cross_up_3d"] = (
        group["ma20_cross_up"].rolling(window=3, min_periods=1).max().fillna(0.0)
    )

    # ma10_cross_up: 1D 10MA 站回信號
    cp_ma10 = group["ma10"].shift(1)
    group["ma10_cross_up"] = ((cp_close <= cp_ma10) & (close > group["ma10"])).astype(float)

    # has_closed_below_ma10_20d: 近 20 日曾收盤跌破 ma10
    is_closed_below_ma10 = (close < group["ma10"]).astype(float)
    group["has_closed_below_ma10_20d"] = (
        is_closed_below_ma10.rolling(window=20, min_periods=1).max().fillna(0.0)
    )

    # ma10_1d_bullish: (ma10 向上且站上) OR (曾跌破今日站回)
    ma10_trending = ((group["ma10_up"] == 1.0) & (close >= group["ma10"])).astype(float)
    ma10_washout_recover = (
        (group["has_closed_below_ma10_20d"] == 1.0) & (group["ma10_cross_up"] == 1.0)
    ).astype(float)
    group["ma10_1d_bullish"] = ((ma10_trending + ma10_washout_recover) >= 1.0).astype(float)

    # ma30_cross_up: 3D 10MA (1D 30MA) 站回信號
    cp_ma30 = group["ma30"].shift(1)
    group["ma30_cross_up"] = ((cp_close <= cp_ma30) & (close > group["ma30"])).astype(float)

    # has_closed_below_ma30_20d: 近 20 日曾收盤跌破 ma30
    is_closed_below_ma30 = (close < group["ma30"]).astype(float)
    group["has_closed_below_ma30_20d"] = (
        is_closed_below_ma30.rolling(window=20, min_periods=1).max().fillna(0.0)
    )

    # ma30_3d_bullish: (ma30 向上且站上) OR (曾跌破今日站回)
    ma30_trending = ((group["ma30_up"] == 1.0) & (close >= group["ma30"])).astype(float)
    ma30_washout_recover = (
        (group["has_closed_below_ma30_20d"] == 1.0) & (group["ma30_cross_up"] == 1.0)
    ).astype(float)
    group["ma30_3d_bullish"] = ((ma30_trending + ma30_washout_recover) >= 1.0).astype(float)

    # Store previous values for inspection
    group["prev_close"] = cp_close
    group["prev_ma20"] = cp_ma20

    # --- Data Integrity: Stuck Data Detection ---
    # Detect if both price and volume have remained exactly identical for 10 consecutive days.
    # This is often a sign of crawler errors or missing historical updates where last values were repeated.
    is_same_as_prev = (close.diff() == 0) & (volume.diff() == 0)
    group["is_stuck_data"] = (
        is_same_as_prev.rolling(window=10, min_periods=10).min().fillna(0.0).astype(float)
    )


def _add_multi_period_and_pattern_indicators(
    group: pd.DataFrame,
    close: pd.Series,
    open_p: pd.Series,
    high: pd.Series,
    low: pd.Series,
    raw_close: pd.Series,
    volume: pd.Series,
) -> None:
    """3D 突破輔助、47D/18D 多週期、raw 系列、影線/K棒型態、前日量。"""
    # 3D Breakout specific indicators
    entity_high = group[["open", "close"]].max(axis=1)
    group["entity_high"] = entity_high
    group["entity_high_max_2d_prev"] = entity_high.rolling(window=2).max().shift(1)
    group["entity_high_max_2d_prev_prev_1"] = group["entity_high_max_2d_prev"].shift(1)
    group["close_prev_1"] = close.shift(1)
    group["close_prev_2"] = close.shift(2)
    group["close_prev_3"] = close.shift(3)
    group["high_prev_1"] = high.shift(1)
    group["low_prev_1"] = low.shift(1)
    group["adj_close"] = close
    group["adj_low"] = low
    group["high_max_2d"] = high.rolling(window=2, min_periods=2).max()
    group["entity_high_prev_1"] = entity_high.shift(1)

    # Raw (unadjusted) high for TradingView-aligned 47D comparisons
    raw_high = pd.to_numeric(group["high"], errors="coerce")
    group["high_47d_prev_raw"] = raw_high.rolling(window=47, min_periods=47).max().shift(47)
    group["high_max_2d_raw"] = raw_high.rolling(window=2, min_periods=2).max()

    # --- New Indicator for 20-day Washout (Close-based) ---
    is_closed_below_ma20 = (close < group["ma20"]).astype(float)
    group["has_closed_below_ma20_20d"] = (
        is_closed_below_ma20.rolling(window=20, min_periods=1).max().fillna(0.0)
    )

    # --- Multi-period K-line indicators (一根K線 = N天) ---
    # 前一根 47D K線的收盤價 = 47 個交易日前的收盤價
    group["close_47d_prev"] = close.shift(47)
    # 前一根 18D K線的收盤價 = 18 個交易日前的收盤價
    group["close_18d_prev"] = close.shift(18)
    # 當前 47D K線的最高價 = 過去 47 天的 rolling max high
    group["high_47d_max"] = high.rolling(window=47, min_periods=47).max()
    # 各週期參考點的 MA200（判定當時是否在 200MA 之上）
    group["ma200_47d_prev"] = group["ma200"].shift(47)
    group["ma200_18d_prev"] = group["ma200"].shift(18)
    group["ma200_3d_prev"] = group["ma200"].shift(3)

    # --- Raw Price Indicators (for TradingView alignment) ---
    group["raw_close"] = raw_close
    group["raw_close_prev_1"] = raw_close.shift(1)
    group["raw_close_prev_3"] = raw_close.shift(3)
    group["ma20_raw"] = raw_close.rolling(window=20, min_periods=20).mean()
    group["ma200_raw"] = raw_close.rolling(window=200, min_periods=200).mean()

    cp_raw_close = group["raw_close_prev_1"]
    cp_ma20_raw = group["ma20_raw"].shift(1)
    group["ma20_raw_cross_up"] = (
        (cp_raw_close <= cp_ma20_raw) & (raw_close > group["ma20_raw"])
    ).astype(float)

    is_closed_below_ma20_raw = (raw_close < group["ma20_raw"]).astype(float)
    group["has_closed_below_ma20_raw_20d"] = (
        is_closed_below_ma20_raw.rolling(window=20, min_periods=1).max().fillna(0.0)
    )
    group["ma200_raw_3d_prev"] = group["ma200_raw"].shift(3)

    # --- Candle shadow / pattern indicators ---
    body_top = pd.concat([open_p, close], axis=1).max(axis=1)
    body_bottom = pd.concat([open_p, close], axis=1).min(axis=1)
    body_length = (body_top - body_bottom).clip(lower=0.001)
    upper_shadow = (high - body_top).clip(lower=0.0)
    lower_shadow = (body_bottom - low).clip(lower=0.0)
    candle_range = high - low

    group["upper_shadow_ratio"] = (upper_shadow / candle_range.replace(0, pd.NA)).fillna(0.0)

    # Shooting star / 倒T線: upper shadow ≥ 2× body, lower shadow ≤ 20% of total range
    # Using candle_range for the lower shadow threshold handles near-doji candles gracefully.
    group["is_shooting_star"] = (
        (upper_shadow >= 2.0 * body_length)
        & (lower_shadow <= candle_range.replace(0, pd.NA).fillna(0) * 0.2)
    ).astype(float)

    # 仙人指路黑K: black candle with upper shadow ≥ 2× body
    group["is_fairy_guide_black"] = ((close < open_p) & (upper_shadow >= 2.0 * body_length)).astype(
        float
    )

    group["is_shooting_star_prev_1"] = group["is_shooting_star"].shift(1).fillna(0.0)
    group["prev_candle_body_mid"] = (open_p.shift(1) + close.shift(1)) / 2.0

    # Previous-day volume helpers
    group["volume_prev_1"] = volume.shift(1)
    group["volume_ma5_prev_1"] = group["volume_ma5"].shift(1)
    group["high_20_prev_1"] = group["high_20"].shift(1)


def _compute_group_indicators(group: pd.DataFrame) -> pd.DataFrame:
    series = _resolve_price_series(group)
    close, open_p, high, low = series["close"], series["open_p"], series["high"], series["low"]
    raw_close, volume = series["raw_close"], series["volume"]

    _add_moving_average_indicators(group, close, volume)
    _add_oscillator_indicators(group, close, open_p, high, low)
    _add_purity_and_blackcandle_indicators(group, close, open_p, high)
    _add_washout_recovery_indicators(group, close, high, low, volume)
    _add_multi_period_and_pattern_indicators(group, close, open_p, high, low, raw_close, volume)
    return group


def _compute_rsi(close: pd.Series, window: int) -> pd.Series:
    delta = close.diff()
    gains = delta.clip(lower=0.0)
    losses = -delta.clip(upper=0.0)
    avg_gain = gains.rolling(window=window, min_periods=window).mean()
    avg_loss = losses.rolling(window=window, min_periods=window).mean()
    rs = avg_gain / avg_loss.replace(0.0, pd.NA)
    rsi = 100.0 - (100.0 / (1.0 + rs))
    return rsi.fillna(100.0).where(avg_gain.notna() | avg_loss.notna())


def _compute_macd(close: pd.Series) -> tuple[pd.Series, pd.Series, pd.Series]:
    ema_fast = close.ewm(span=12, adjust=False, min_periods=12).mean()
    ema_slow = close.ewm(span=26, adjust=False, min_periods=26).mean()
    macd_line = ema_fast - ema_slow
    macd_signal = macd_line.ewm(span=9, adjust=False, min_periods=9).mean()
    macd_hist = macd_line - macd_signal
    return macd_line, macd_signal, macd_hist


def _compute_kd(high: pd.Series, low: pd.Series, close: pd.Series) -> tuple[pd.Series, pd.Series]:
    lowest_low = low.rolling(window=9, min_periods=9).min()
    highest_high = high.rolling(window=9, min_periods=9).max()
    denominator = (highest_high - lowest_low).replace(0.0, pd.NA)
    rsv = ((close - lowest_low) / denominator * 100.0).fillna(0.0)

    # 用 numpy array 取代 pandas .iloc 逐行存取，減少 Python/pandas 層開銷約 5–8x
    ll_arr = lowest_low.to_numpy()
    hh_arr = highest_high.to_numpy()
    rsv_arr = rsv.to_numpy()
    n = len(rsv_arr)

    k_arr = np.empty(n)
    d_arr = np.empty(n)
    k_arr[:] = np.nan
    d_arr[:] = np.nan
    k_prev = 50.0
    d_prev = 50.0

    for i in range(n):
        if np.isnan(ll_arr[i]) or np.isnan(hh_arr[i]):
            continue
        k_prev = (2.0 / 3.0) * k_prev + (1.0 / 3.0) * rsv_arr[i]
        d_prev = (2.0 / 3.0) * d_prev + (1.0 / 3.0) * k_prev
        k_arr[i] = k_prev
        d_arr[i] = d_prev

    return (
        pd.Series(k_arr, index=close.index, dtype="float64"),
        pd.Series(d_arr, index=close.index, dtype="float64"),
    )


def _compute_atr(high: pd.Series, low: pd.Series, close: pd.Series, window: int) -> pd.Series:
    prev_close = close.shift(1)
    true_range = pd.concat(
        [
            high - low,
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return true_range.rolling(window=window, min_periods=window).mean()


def _compute_bollinger_bands(
    close: pd.Series, window: int, stddev: float
) -> tuple[pd.Series, pd.Series, pd.Series]:
    middle = close.rolling(window=window, min_periods=window).mean()
    band_std = close.rolling(window=window, min_periods=window).std(ddof=0)
    upper = middle + band_std * stddev
    lower = middle - band_std * stddev
    return middle, upper, lower
