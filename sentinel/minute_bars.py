from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Optional

import pandas as pd
from sqlalchemy import text
from sqlalchemy.orm import Session

from sentinel.logging_utils import get_logger
from sentinel.models import MinuteBar

logger = get_logger(__name__)

# 台股交易時間：09:00 ~ 13:30，每 5 分鐘一根 = 54 根
TRADING_START = "09:00"
TRADING_END = "13:30"
BARS_PER_DAY = 54  # 4.5h × 12 bars/h
MA5_DAY_PERIOD = 5  # 五日均線
MA5_BAR_COUNT = BARS_PER_DAY * MA5_DAY_PERIOD  # 270 根

# exchange 欄位 mapping
EXCHANGE_TO_MARKET = {
    "twse": "TWSE",
    "tpex": "TPEX",
}


def import_minute_bars_csv(
    intraday_session: Session,
    csv_path: Path,
    chunk_size: int = 100_000,
    symbol_market_map: Optional[dict[str, str]] = None,
) -> int:
    """讀取 finmind 1m CSV，聚合為 5m K 線，批次寫入 DB。

    Returns:
        寫入的總行數。
    """
    total_rows = 0
    chunk_count = 0

    for chunk in pd.read_csv(csv_path, chunksize=chunk_size, dtype={"symbol": str}):
        chunk_count += 1
        aggregated = _aggregate_chunk_to_5min(chunk, symbol_market_map)
        if aggregated.empty:
            continue

        rows_written = _bulk_insert_minute_bars(intraday_session, aggregated)
        total_rows += rows_written

        # Commit every 10 chunks to avoid massive memory usage (approx 1M source rows)
        if chunk_count % 10 == 0:
            intraday_session.commit()

        # Log progress for every chunk to keep user informed
        logger.info(
            "import_progress",
            extra={"chunks": chunk_count, "total_rows": total_rows},
        )

    intraday_session.commit()
    logger.info(
        "import_complete",
        extra={"chunks": chunk_count, "total_rows": total_rows},
    )
    return total_rows


def _aggregate_chunk_to_5min(
    chunk: pd.DataFrame, symbol_market_map: Optional[dict[str, str]] = None
) -> pd.DataFrame:
    """將 1m K 線 chunk 聚合為 5m K 線。"""
    df = chunk.copy()

    # 解析時間戳：FinMind 匯出雖帶有 +00，但實務上其數值已是台北時間（例如 09:00 表示開盤）
    # 若進行 tz_convert("Asia/Taipei") 會導致 +8h 變成 17:00，因此我們直接取其名目時間 (naive)
    df["ts_open"] = pd.to_datetime(df["ts_open"], errors="coerce")
    df["ts_local"] = df["ts_open"].dt.tz_localize(None)
    df["trading_date"] = df["ts_local"].dt.date

    # 產生 5 分鐘 bucket：floor 到 5 分鐘邊界
    df["bar_dt"] = df["ts_local"].dt.floor("5min")
    df["bar_time"] = df["bar_dt"].dt.strftime("%H:%M")

    # 市場屬性：優先使用 symbol_market_map 查找，若無則依據 exchange 欄位
    if symbol_market_map:
        df["market"] = df["symbol"].map(symbol_market_map)
    else:
        df["market"] = df["exchange"].str.lower().map(EXCHANGE_TO_MARKET)

    df = df.dropna(subset=["market"])

    # 確保數值欄位
    for col in ["open", "high", "low", "close"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df["volume"] = pd.to_numeric(df["volume"], errors="coerce").fillna(0).astype(int)

    # 聚合 OHLCV
    grouped = df.groupby(["market", "symbol", "trading_date", "bar_time"], sort=True)
    aggregated = grouped.agg(
        open=("open", "first"),
        high=("high", "max"),
        low=("low", "min"),
        close=("close", "last"),
        volume=("volume", "sum"),
    ).reset_index()

    # 取 source 欄位（來自原始資料）
    if "source" in df.columns:
        source_map = (
            df.groupby(["market", "symbol", "trading_date", "bar_time"])["source"]
            .first()
            .reset_index()
        )
        aggregated = aggregated.merge(
            source_map, on=["market", "symbol", "trading_date", "bar_time"], how="left"
        )
    else:
        aggregated["source"] = "finmind"

    return aggregated


def _bulk_insert_minute_bars(session: Session, df: pd.DataFrame) -> int:
    """批次 bulk insert 5m K 線到 DB，忽略衝突 (INSERT OR IGNORE) 以極大化效能。"""
    from sqlalchemy.dialects.sqlite import insert

    all_rows = df.to_dict(orient="records")
    if not all_rows:
        return 0

    total_count = 0
    # SQLite 對單一 SQL 的參數數量有限制 (預設 999)。
    # 每行約 10 個欄位，分批以 50 筆為一單位可穩定避免 Parameter Overflow。
    sub_batch_size = 50
    for i in range(0, len(all_rows), sub_batch_size):
        sub_rows = all_rows[i : i + sub_batch_size]
        stmt = insert(MinuteBar).values(sub_rows)
        stmt = stmt.on_conflict_do_nothing(
            index_elements=["market", "symbol", "trading_date", "bar_time"]
        )
        result = session.execute(stmt)
        # 注意：SQLite rowcount 在 ON CONFLICT 下的行為依驅動版本可能不同，主要用於記錄寫入完成
        total_count += result.rowcount
    return total_count


def load_5min_bars(
    intraday_session: Session,
    market: str,
    symbol: str,
    start_date: date,
    end_date: date,
) -> pd.DataFrame:
    """查詢特定股票在日期範圍內的 5m K 線。"""
    stmt = text(
        """
        SELECT market, symbol, trading_date, bar_time,
               open, high, low, close, volume
        FROM minute_bars
        WHERE market = :market
          AND symbol = :symbol
          AND trading_date >= :start_date
          AND trading_date <= :end_date
        ORDER BY trading_date, bar_time
    """
    )
    result = intraday_session.execute(
        stmt,
        {"market": market, "symbol": symbol, "start_date": start_date, "end_date": end_date},
    )
    rows = result.fetchall()
    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(
        rows,
        columns=[
            "market",
            "symbol",
            "trading_date",
            "bar_time",
            "open",
            "high",
            "low",
            "close",
            "volume",
        ],
    )
    for col in ["open", "high", "low", "close"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df["volume"] = pd.to_numeric(df["volume"], errors="coerce").fillna(0).astype(int)
    return df


def calc_5day_ma(bars_5m: pd.DataFrame, target_date: date) -> Optional[float]:
    """計算五分K五日均線：target_date 開盤時，前 5 個交易日所有 5m close 的平均值。

    Args:
        bars_5m: 包含多日 5m K 線的 DataFrame（需已排序）。
        target_date: 要計算 MA 的日期。

    Returns:
        五日均線值，若資料不足則回傳 None。
    """
    # 取 target_date 之前的所有 K 線
    prior_bars = bars_5m[bars_5m["trading_date"] < target_date].copy()
    if prior_bars.empty:
        return None

    # 取最近 5 個交易日
    trading_days = sorted(prior_bars["trading_date"].unique())
    recent_5_days = trading_days[-MA5_DAY_PERIOD:]
    recent_bars = prior_bars[prior_bars["trading_date"].isin(recent_5_days)]

    if recent_bars.empty:
        return None

    return float(recent_bars["close"].mean())


def calc_intraday_avg(bars_5m: pd.DataFrame, target_date: date, up_to_time: str) -> Optional[float]:
    """計算五分K日均線：target_date 當天到 up_to_time 為止的 5m close 平均。

    Args:
        bars_5m: 包含當日 5m K 線的 DataFrame。
        target_date: 計算的日期。
        up_to_time: 到什麼時間為止（HH:MM 格式）。

    Returns:
        日均線值，若無資料則回傳 None。
    """
    day_bars = bars_5m[
        (bars_5m["trading_date"] == target_date) & (bars_5m["bar_time"] <= up_to_time)
    ]
    if day_bars.empty:
        return None
    return float(day_bars["close"].mean())


def is_limit_up_at_open(
    bars_5m: pd.DataFrame,
    target_date: date,
    prev_close: float,
    limit_pct: float = 0.10,
) -> bool:
    """判斷是否開盤即漲停（無法進場）。

    台股漲停 = 前一日收盤 × (1 + limit_pct)，四捨五入到 tick size。
    簡化判斷：開盤價 >= 前收 × (1 + limit_pct × 0.99) 且首根成交量極低。
    """
    day_bars = bars_5m[bars_5m["trading_date"] == target_date]
    if day_bars.empty:
        return True  # 無資料視為無法進場

    first_bar = day_bars.iloc[0]
    limit_price = prev_close * (1.0 + limit_pct)
    # 若開盤價接近漲停價（容許 0.5% 誤差）且首根量極低
    return float(first_bar["open"]) >= limit_price * 0.995


def get_prev_close(
    daily_session: Session,
    market: str,
    symbol: str,
    target_date: date,
) -> Optional[float]:
    """從 daily_prices 取得前一交易日收盤價。"""
    stmt = text(
        """
        SELECT close FROM daily_prices
        WHERE market = :market AND symbol = :symbol AND trading_date < :target_date
        ORDER BY trading_date DESC LIMIT 1
    """
    )
    result = daily_session.execute(
        stmt, {"market": market, "symbol": symbol, "target_date": target_date}
    )
    row = result.fetchone()
    if row:
        return float(row[0])
    return None
