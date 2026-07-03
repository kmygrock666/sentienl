from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
from sqlalchemy import text
from sqlalchemy.orm import Session

from sentinel.logging_utils import get_logger

logger = get_logger(__name__)


def generate_tomorrow_star_signals(
    daily_session: Session,
    intraday_session: Session,
    start_date: date,
    end_date: date,
    top_n: int = 300,
) -> pd.DataFrame:
    """
    產生「明日之星」策略的歷史訊號框架。
    模擬每天 13:00 的選股狀態（使用分鐘 K 線重現），將符合條件的個股納入訊號。

    條件：
    1. 13:00 時點股價 <= 1000
    2. 13:00 漲幅 >= 7.5% 且 收紅K (13:00 收盤 > 09:00 開盤)
    3. 13:00 累積量 >= 1.5 * 前五日平均量
    4. 午盤爆發比 (12:00~13:00 量 / 09:00~12:00 量) >= 1.0
    """
    signals = []

    # 取得回測期間所有的實際交易日（從 daily_prices）
    stmt_dates = text(
        """
        SELECT DISTINCT trading_date FROM daily_prices
        WHERE trading_date >= :start_date AND trading_date <= :end_date
        ORDER BY trading_date
    """
    )
    dates = [
        row[0]
        for row in daily_session.execute(
            stmt_dates, {"start_date": start_date, "end_date": end_date}
        ).fetchall()
    ]

    if not dates:
        return pd.DataFrame()

    for current_date in dates:
        if isinstance(current_date, str):
            current_date = date.fromisoformat(current_date)

        # 取得前一個交易日
        stmt_prev_date = text(
            """
            SELECT trading_date FROM daily_prices
            WHERE trading_date < :curr_date
            ORDER BY trading_date DESC LIMIT 1
        """
        )
        prev_date_res = daily_session.execute(stmt_prev_date, {"curr_date": current_date}).scalar()
        if not prev_date_res:
            continue

        prev_date = prev_date_res
        if isinstance(prev_date, str):
            prev_date = date.fromisoformat(prev_date)

        # 取得前日成交量前 top_n 的標的
        stmt_targets = text(
            """
            SELECT market, symbol, close as prev_close
            FROM daily_prices
            WHERE trading_date = :prev_date
            ORDER BY volume DESC
            LIMIT :top_n
        """
        )
        targets = daily_session.execute(
            stmt_targets, {"prev_date": prev_date, "top_n": top_n}
        ).fetchall()
        if not targets:
            continue

        target_map = {(row.market, row.symbol): float(row.prev_close) for row in targets}
        target_keys = list(target_map.keys())

        # 計算這 N 檔個股的前 5 日平均量：直接撈區間資料後用 pandas 分組，
        # 避免 text() 的 tuple IN 子句在不同 DB 方言間的相容性問題。
        start_5d = prev_date - timedelta(days=15)
        stmt_vols = text(
            """
            SELECT market, symbol, trading_date, volume
            FROM daily_prices
            WHERE trading_date BETWEEN :start_5d AND :prev_date
        """
        )
        df_vols = pd.read_sql(
            stmt_vols, daily_session.bind, params={"start_5d": start_5d, "prev_date": prev_date}
        )

        if df_vols.empty:
            continue

        df_vols = df_vols[df_vols.set_index(["market", "symbol"]).index.isin(target_keys)]
        df_vols = df_vols.sort_values(
            ["market", "symbol", "trading_date"], ascending=[True, True, False]
        )
        # 取前 5 筆
        df_vols = df_vols.groupby(["market", "symbol"]).head(5)
        avg_vols = df_vols.groupby(["market", "symbol"])["volume"].mean().to_dict()

        # 取得這 N 檔標的在 current_date 的 13:00 (含) 之前的分鐘 K 線
        # Pandas SQL read
        stmt_mb = text(
            """
            SELECT market, symbol, bar_time, open, close, volume
            FROM minute_bars
            WHERE trading_date = :curr_date
              AND bar_time <= '13:00'
        """
        )
        df_mb = pd.read_sql(stmt_mb, intraday_session.bind, params={"curr_date": current_date})
        if df_mb.empty:
            continue

        df_mb = df_mb[df_mb.set_index(["market", "symbol"]).index.isin(target_keys)]
        if df_mb.empty:
            continue

        # 運算 13:00 狀態
        grouped = df_mb.groupby(["market", "symbol"])

        for (market, symbol), group in grouped:
            group = group.sort_values("bar_time")
            if group.empty:
                continue

            open_price = float(group.iloc[0]["open"])
            close_price = float(group.iloc[-1]["close"])

            # 計算分段量能
            vol_morning = group[group["bar_time"] <= "12:00"]["volume"].sum()
            vol_afternoon = group[(group["bar_time"] > "12:00") & (group["bar_time"] <= "13:00")][
                "volume"
            ].sum()
            vol_total = vol_morning + vol_afternoon

            avg_vol_5d = avg_vols.get((market, symbol), 0)
            prev_close = target_map.get((market, symbol), 0)

            if prev_close <= 0 or avg_vol_5d <= 0:
                continue

            gain = (close_price / prev_close) - 1.0

            # Rule 1
            if close_price > 1000:
                continue

            # Rule 2
            if gain < 0.075 or close_price <= open_price:
                continue

            # Rule 3
            if vol_total < (avg_vol_5d * 1.5):
                continue

            # Rule 4: 午盤爆發比 >= 1.0
            if vol_morning <= 0 or (vol_afternoon / vol_morning) < 1.0:
                continue

            # 符合所有條件，納入訊號
            vol_surge_ratio = vol_afternoon / vol_morning

            signals.append(
                {
                    "market": market,
                    "symbol": str(symbol),
                    "trading_date": current_date,
                    "strategy_id": "tomorrow_star",
                    "strategy_name": "明日之星 (Historical 13:00)",
                    "close_1300": close_price,
                    "gain_1300": gain,
                    "vol_total_1300": vol_total,
                    "vol_surge_ratio": vol_surge_ratio,
                }
            )

    if not signals:
        return pd.DataFrame()

    df_signals = pd.DataFrame(signals)
    return df_signals
