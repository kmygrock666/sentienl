from __future__ import annotations

from datetime import date
from typing import Optional

import pandas as pd
from sqlalchemy import func
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from sentinel.models import InstitutionalFlow, Stock

_INSTITUTIONAL_COLUMNS = ["日期", "外資", "投信", "自營商", "合計"]

_NET_COLUMN_WHITELIST = frozenset(
    {"foreign_net", "investment_trust_net", "dealer_net", "total_net"}
)
_RANKING_COLUMNS = ["市場", "代號", "名稱", "買賣超(張)"]
_STREAK_COLUMNS = ["市場", "代號", "名稱", "連買天數", "期間累計(張)"]


def get_institutional_flow(
    engine: Engine, market: str, symbol: str, days: int = 10
) -> pd.DataFrame:
    """近 N 個交易日的法人買賣超。欄位：日期, 外資, 投信, 自營商, 合計（張）。"""

    def _to_lots(value: int | None) -> int | None:
        return int(value / 1000) if value is not None else None

    with Session(engine) as s:
        rows = (
            s.query(InstitutionalFlow)
            .filter(InstitutionalFlow.market == market, InstitutionalFlow.symbol == symbol)
            .order_by(InstitutionalFlow.trading_date.desc())
            .limit(days)
            .all()
        )
    if not rows:
        return pd.DataFrame(columns=_INSTITUTIONAL_COLUMNS)
    df = pd.DataFrame(
        [
            {
                "日期": r.trading_date,
                "外資": _to_lots(r.foreign_net),
                "投信": _to_lots(r.investment_trust_net),
                "自營商": _to_lots(r.dealer_net),
                "合計": _to_lots(r.total_net),
            }
            for r in rows
        ]
    )
    # 缺值保持為 NA（避免 None 混入時整欄被轉為 float）
    for col in _INSTITUTIONAL_COLUMNS[1:]:
        df[col] = df[col].astype("Int64")
    return df


def get_institutional_dates(engine: Engine, limit: int = 30) -> list[date]:
    """institutional_flows 中存在資料的交易日（新→舊，最多 limit 個）。"""
    with Session(engine) as s:
        rows = (
            s.query(InstitutionalFlow.trading_date.distinct())
            .order_by(InstitutionalFlow.trading_date.desc())
            .limit(limit)
            .all()
        )
    return [r[0] for r in rows]


def get_institutional_ranking(
    engine: Engine,
    trading_date: date,
    net_column: str,
    market: str | None = None,
    ascending: bool = False,
    limit: int = 20,
) -> pd.DataFrame:
    """單日法人買賣超排行。欄位：市場, 代號, 名稱, 買賣超(張)。

    買超排行（ascending=False）只收正值、賣超排行只收負值，
    避免排行尾端出現反向值。net_column 必須在白名單內（防注入、防打錯）。
    """
    if net_column not in _NET_COLUMN_WHITELIST:
        raise ValueError(
            f"net_column 必須是 {sorted(_NET_COLUMN_WHITELIST)} 之一，收到：{net_column!r}"
        )
    net_col = getattr(InstitutionalFlow, net_column)
    with Session(engine) as s:
        q = (
            s.query(
                InstitutionalFlow.market,
                InstitutionalFlow.symbol,
                Stock.name,
                net_col.label("net"),
            )
            .outerjoin(
                Stock,
                (Stock.market == InstitutionalFlow.market)
                & (Stock.symbol == InstitutionalFlow.symbol),
            )
            .filter(InstitutionalFlow.trading_date == trading_date)
        )
        if market:
            q = q.filter(InstitutionalFlow.market == market)
        if ascending:
            q = q.filter(net_col < 0).order_by(net_col.asc())
        else:
            q = q.filter(net_col > 0).order_by(net_col.desc())
        rows = q.limit(limit).all()
    if not rows:
        return pd.DataFrame(columns=_RANKING_COLUMNS)
    return pd.DataFrame(
        [
            {
                "市場": r.market,
                "代號": r.symbol,
                "名稱": r.name or "",
                "買賣超(張)": int(r.net / 1000),
            }
            for r in rows
        ]
    )


def get_foreign_streak_ranking(
    engine: Engine,
    end_date: date,
    days: int = 10,
    market: str | None = None,
    limit: int = 20,
) -> pd.DataFrame:
    """外資連續買超天數排行（以 end_date 往回 days 個資料日計算）。

    streak 定義：從 end_date 往回、foreign_net > 0 連續的天數
    （中斷即停，缺資料日視為中斷）；只列 streak >= 2。
    期間累計 = streak 期間的 foreign_net 加總（張）。
    """
    with Session(engine) as s:
        date_rows = (
            s.query(InstitutionalFlow.trading_date.distinct())
            .filter(InstitutionalFlow.trading_date <= end_date)
            .order_by(InstitutionalFlow.trading_date.desc())
            .limit(days)
            .all()
        )
        window = [r[0] for r in date_rows]  # 新 → 舊
        if not window:
            return pd.DataFrame(columns=_STREAK_COLUMNS)
        q = (
            s.query(
                InstitutionalFlow.market,
                InstitutionalFlow.symbol,
                InstitutionalFlow.trading_date,
                InstitutionalFlow.foreign_net,
                Stock.name,
            )
            .outerjoin(
                Stock,
                (Stock.market == InstitutionalFlow.market)
                & (Stock.symbol == InstitutionalFlow.symbol),
            )
            .filter(InstitutionalFlow.trading_date.in_(window))
        )
        if market:
            q = q.filter(InstitutionalFlow.market == market)
        rows = q.all()
    if not rows:
        return pd.DataFrame(columns=_STREAK_COLUMNS)

    by_stock: dict[tuple[str, str], dict] = {}
    for r in rows:
        entry = by_stock.setdefault((r.market, r.symbol), {"name": r.name or "", "nets": {}})
        entry["nets"][r.trading_date] = r.foreign_net

    records = []
    for (mkt, symbol), entry in by_stock.items():
        streak, total = 0, 0
        for d in window:  # 從最近的資料日往回走
            net = entry["nets"].get(d)
            if net is None or net <= 0:
                break
            streak += 1
            total += net
        if streak >= 2:
            records.append(
                {
                    "市場": mkt,
                    "代號": symbol,
                    "名稱": entry["name"],
                    "連買天數": streak,
                    "期間累計(張)": int(total / 1000),
                }
            )
    if not records:
        return pd.DataFrame(columns=_STREAK_COLUMNS)
    df = pd.DataFrame(records).sort_values(
        ["連買天數", "期間累計(張)"], ascending=[False, False], kind="stable"
    )
    return df.head(limit).reset_index(drop=True)


def get_latest_institutional_date(engine: Engine) -> Optional[date]:
    """查詢 InstitutionalFlow 最新 trading_date；無資料時回傳 None。"""
    with Session(engine) as s:
        return s.query(func.max(InstitutionalFlow.trading_date)).scalar()
