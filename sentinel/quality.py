from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import pandas as pd

VALIDITY_RULE = "validity"
RULE_HIGH_GTE_MAX_OPEN_CLOSE = "high_gte_max_open_close"
RULE_LOW_LTE_MIN_OPEN_CLOSE = "low_lte_min_open_close"
RULE_VOLUME_NON_NEGATIVE = "volume_non_negative"
RULE_PRICE_CHANGE_SPIKE = "price_change_spike"

# Taiwan TWSE/TPEX daily limit is ±10%.  We flag rows that deviate more than
# PRICE_SPIKE_THRESHOLD from the previous session's close as likely bad data.
# Set conservatively at 20% (double the limit) to avoid false positives from
# halted stocks or ex-rights adjustments.
PRICE_SPIKE_THRESHOLD = 0.20


@dataclass
class DailyPriceValidationResult:
    valid_prices: pd.DataFrame
    invalid_prices: pd.DataFrame


def validate_daily_prices(
    prices: pd.DataFrame,
    reference_prices: Optional[pd.DataFrame] = None,
    spike_threshold: float = PRICE_SPIKE_THRESHOLD,
) -> DailyPriceValidationResult:
    """Validate a batch of daily price rows.

    Args:
        prices: Newly fetched price rows to validate.
        reference_prices: Historical price dataset used to look up each
            symbol's previous-session close for cross-day spike detection.
            When omitted (or when no prior close is found for a symbol),
            the spike check is skipped for that row.
        spike_threshold: Maximum allowed fractional change from previous close
            (e.g. 0.20 = 20%).  Rows exceeding this are quarantined.
    """
    if prices.empty:
        return DailyPriceValidationResult(
            valid_prices=prices.copy(),
            invalid_prices=prices.copy().assign(violations=pd.Series(dtype=object), violated_rule=pd.Series(dtype=str)),
        )

    frame = prices.copy().reset_index(drop=True)
    violations: list[list[str]] = [[] for _ in range(len(frame.index))]

    # ── 單日 OHLC 一致性檢查 ──────────────────────────────────────────────
    checks = {
        RULE_HIGH_GTE_MAX_OPEN_CLOSE: frame["high"] < frame[["open", "close"]].max(axis=1),
        RULE_LOW_LTE_MIN_OPEN_CLOSE: frame["low"] > frame[["open", "close"]].min(axis=1),
        RULE_VOLUME_NON_NEGATIVE: frame["volume"] < 0,
    }

    for rule_name, mask in checks.items():
        for idx, violated in enumerate(mask.fillna(False).tolist()):
            if violated:
                violations[idx].append(rule_name)

    # ── 跨日價格暴漲/暴跌偵測 ─────────────────────────────────────────────
    if reference_prices is not None and not reference_prices.empty:
        spike_mask = _detect_price_spikes(frame, reference_prices, spike_threshold)
        for idx, spiked in enumerate(spike_mask.tolist()):
            if spiked:
                violations[idx].append(RULE_PRICE_CHANGE_SPIKE)

    frame["violations"] = violations
    invalid_mask = frame["violations"].map(bool)

    valid_prices = frame.loc[~invalid_mask].copy().drop(columns=["violations"], errors="ignore")
    invalid_prices = frame.loc[invalid_mask].copy()
    if not invalid_prices.empty:
        invalid_prices["violated_rule"] = VALIDITY_RULE

    return DailyPriceValidationResult(valid_prices=valid_prices, invalid_prices=invalid_prices)


def _detect_price_spikes(
    frame: pd.DataFrame,
    reference_prices: pd.DataFrame,
    threshold: float,
) -> pd.Series:
    """Return a bool Series (same index as frame) marking rows whose close
    deviates more than `threshold` from the most recent prior-session close.

    Reference is built from both `reference_prices` (historical CSV) and the
    current `frame` itself so that within-batch cross-day comparisons use the
    same data source.  Rows with no prior close are NOT flagged (safe default).

    Bulk-anomaly guard: if more than 30% of a trading date's rows are flagged,
    the flags for that date are cleared — this indicates a reference data
    failure (e.g. holiday gap, ex-dividend wave) rather than genuine bad data.
    """
    # Build combined reference: historical CSV + current batch
    combined_ref = pd.concat([reference_prices, frame], ignore_index=True)
    combined_ref["trading_date"] = pd.to_datetime(combined_ref["trading_date"]).dt.date
    # Keep only the most recent close per (market, symbol, trading_date)
    combined_ref = (
        combined_ref
        .sort_values("trading_date")
        .drop_duplicates(subset=["market", "symbol", "trading_date"], keep="last")
    )

    frame_dates = pd.to_datetime(frame["trading_date"]).dt.date
    spike_flags = pd.Series(False, index=frame.index)

    ref_grouped = {
        key: grp.sort_values("trading_date")
        for key, grp in combined_ref.groupby(["market", "symbol"])
    }

    for idx, row in frame.iterrows():
        key = (row["market"], row["symbol"])
        ref_grp = ref_grouped.get(key)
        if ref_grp is None or ref_grp.empty:
            continue

        row_date = frame_dates.iloc[idx] if hasattr(frame_dates, "iloc") else pd.to_datetime(row["trading_date"]).date()
        prior = ref_grp[ref_grp["trading_date"] < row_date]
        if prior.empty:
            continue

        prev_close = prior.iloc[-1]["close"]
        if pd.isna(prev_close) or prev_close == 0:
            continue

        current_close = row["close"]
        if pd.isna(current_close):
            continue

        change = abs(current_close - prev_close) / abs(prev_close)
        if change > threshold:
            spike_flags.iloc[idx] = True

    # Bulk-anomaly guard: clear flags for dates where >15% of stocks are flagged
    # (indicates reference failure, not genuine bad data — e.g. holiday gap,
    # ex-dividend wave, typhoon closure)
    frame_dates_series = pd.to_datetime(frame["trading_date"]).dt.date
    for date, grp_idx in frame.groupby(frame_dates_series).groups.items():
        total = len(grp_idx)
        flagged = spike_flags.loc[grp_idx].sum()
        if total > 0 and flagged / total > 0.15:
            spike_flags.loc[grp_idx] = False

    return spike_flags
