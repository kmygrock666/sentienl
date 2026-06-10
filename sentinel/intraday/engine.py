from __future__ import annotations

import logging
from datetime import date
from typing import Any, Dict, List

from sqlalchemy import and_, desc, func, select
from sqlalchemy.orm import Session

from sentinel.intraday.fetcher import MISFetcher, parse_mis_data
from sentinel.models import DailyPrice, IntradayIndicator, IntradaySnapshot

logger = logging.getLogger(__name__)

# Tomorrow's Star 策略參數
DEFAULT_TOP_N = 300  # 以昨日成交量取前 N 檔為掃描對象
DEFAULT_MIN_GAIN = 0.075  # 最終漲幅門檻（7.5%）
MAX_PRICE = 1000.0  # 股價上限，排除高價股
INTRADAY_MIN_GAIN = 0.03  # 盤中初步漲幅門檻（3%）
VOLUME_RATIO_MIN = 1.5  # 成交量需達 5 日均量的倍數
GREAT_POWER_LOCK_RATIO = 3.0  # 最後一筆量 ≥ 鎖單量/此值 視為大戶力道
VOLUME_AVG_WINDOW_DAYS = 5  # 均量計算視窗


def run_tomorrow_star_scan(
    session: Session,
    top_n: int = DEFAULT_TOP_N,
    min_gain: float = DEFAULT_MIN_GAIN,
) -> List[Dict[str, Any]]:
    """
    Run the "Tomorrow's Star" intraday strategy scan.
    Identifies momentum stocks at 13:00 session.
    """
    # 1. Get targets: top stocks by yesterday's volume
    # Get the latest trading date in the DB (strictly before today)
    today = date.today()
    latest_date_stmt = (
        select(DailyPrice.trading_date)
        .where(DailyPrice.trading_date < today)
        .order_by(desc(DailyPrice.trading_date))
        .limit(1)
    )
    latest_date = session.execute(latest_date_stmt).scalar()

    if not latest_date:
        logger.error("No historical data to determine target stocks.")
        return []

    target_stocks_stmt = (
        select(DailyPrice.market, DailyPrice.symbol)
        .where(and_(DailyPrice.trading_date == latest_date, func.length(DailyPrice.symbol) == 4))
        .order_by(desc(DailyPrice.volume))
        .limit(top_n)
    )
    targets = session.execute(target_stocks_stmt).all()
    symbols = [t.symbol for t in targets]
    markets = [t.market for t in targets]

    # 2. Fetch real-time data from MIS
    fetcher = MISFetcher()
    raw_msgs = fetcher.fetch_all(symbols, markets)

    # 3. Fetch 5-day volume statistics for targets
    # We need the last 5 TRADING days strictly.
    subq = (
        select(
            DailyPrice.market,
            DailyPrice.symbol,
            DailyPrice.volume,
            func.row_number()
            .over(
                partition_by=[DailyPrice.market, DailyPrice.symbol],
                order_by=DailyPrice.trading_date.desc(),
            )
            .label("rn"),
        )
        .where(and_(DailyPrice.trading_date < today, DailyPrice.symbol.in_(symbols)))
        .subquery()
    )

    vol_stats_stmt = (
        select(subq.c.market, subq.c.symbol, func.avg(subq.c.volume).label("avg_vol_5d"))
        .where(subq.c.rn <= VOLUME_AVG_WINDOW_DAYS)
        .group_by(subq.c.market, subq.c.symbol)
    )

    vol_records = session.execute(vol_stats_stmt).all()
    avg_volumes = {(v.market, v.symbol): v.avg_vol_5d for v in vol_records}

    # 4. Load Baseline Snapshots for volume ratio calculation
    # We prefer "12:00", but we'll take the latest one up to "12:01" as a fallback.
    subq_snap = (
        select(
            IntradaySnapshot.market,
            IntradaySnapshot.symbol,
            IntradaySnapshot.cumulative_volume,
            func.row_number()
            .over(
                partition_by=[IntradaySnapshot.market, IntradaySnapshot.symbol],
                order_by=IntradaySnapshot.snapshot_time.desc(),
            )
            .label("rn"),
        )
        .where(
            and_(IntradaySnapshot.trading_date == today, IntradaySnapshot.snapshot_time <= "12:00")
        )
        .subquery()
    )
    snap_stmt = select(subq_snap.c.market, subq_snap.c.symbol, subq_snap.c.cumulative_volume).where(
        subq_snap.c.rn == 1
    )

    snapshots = {
        (s.market, s.symbol): s.cumulative_volume for s in session.execute(snap_stmt).all()
    }

    # 5. Load historical Win Rates (Phase 1 indicators)
    ind_stmt = select(IntradayIndicator).where(
        IntradayIndicator.indicator_name == "overnight_win_rate"
    )
    indicators = {(i.market, i.symbol): i for i in session.execute(ind_stmt).scalars().all()}

    # 6. Apply strategy rules
    results = []
    for msg in raw_msgs:
        p = parse_mis_data(msg)
        if not p["symbol"] or p["prev_close"] == 0:
            continue

        gain = (p["close"] - p["prev_close"]) / p["prev_close"]

        # Rule 1: Price <= 1000
        if p["close"] > MAX_PRICE:
            continue

        # Rule 2: Gain >= 3% AND Red K (Close > Open)
        if gain < INTRADAY_MIN_GAIN or p["close"] <= p["open"]:
            continue

        # Rule 3: Volume >= 1.5 * 5-day Average Volume
        avg_v5 = float(avg_volumes.get((p["market"], p["symbol"]), 0))
        if avg_v5 > 0 and p["volume"] < (avg_v5 * VOLUME_RATIO_MIN):
            continue

        # Rule 4: Previous core logic (Gain >= min_gain) - optional if user wants to override
        if gain < min_gain:
            continue

        # Volume Surge Ratio (Snapshot-based for 13:00 scan)
        vol_surge_ratio = 0.0
        snapshot_v = snapshots.get((p["market"], p["symbol"]))
        if snapshot_v and snapshot_v > 0:
            afternoon_vol = p["volume"] - snapshot_v
            vol_surge_ratio = afternoon_vol / snapshot_v

        # Snapshot-based Great Power check
        is_great_power = False
        locked_vol = 0
        if p["close"] == p["limit_up"] and p["best_bid_volume"].isdigit():
            locked_vol = int(p["best_bid_volume"])

        if p["last_trade_volume"] > 0 and locked_vol > 0:
            if p["last_trade_volume"] >= (locked_vol / GREAT_POWER_LOCK_RATIO):
                is_great_power = True

        win_rate = 0.0
        ind = indicators.get((p["market"], p["symbol"]))
        if ind:
            win_rate = float(ind.value)

        # Custom score heuristic
        score = float(win_rate) * (1.0 + float(vol_surge_ratio))

        # Volume Ratio (Current vs MA5)
        vol_ratio = 0.0
        if avg_v5 > 0:
            vol_ratio = p["volume"] / avg_v5

        results.append(
            {
                "symbol": p["symbol"],
                "name": p["name"],
                "market": p["market"],
                "close": p["close"],
                "gain": gain,
                "volume": p["volume"],
                "avg_vol_5d": float(avg_v5),
                "vol_ratio": float(vol_ratio),
                "vol_surge_ratio": float(vol_surge_ratio),
                "is_limit_up": p["close"] == p["limit_up"],
                "is_great_power": is_great_power,
                "win_rate": float(win_rate),
                "score": score,
            }
        )

    # Sort by heuristic score
    results.sort(key=lambda x: x["score"], reverse=True)
    return results[:10]
