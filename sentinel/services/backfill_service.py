from __future__ import annotations

from datetime import date
from typing import Callable, List, Optional

from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from sentinel.config import Settings
from sentinel.datasources.providers import fetch_yahoo_historical
from sentinel.datasources.stock_master import load_stock_master
from sentinel.storage import load_price_dataset, save_price_dataset, upsert_prices
from sentinel.storage.persistence import upsert_daily_prices


def backfill_yahoo_prices(
    *,
    settings: Settings,
    engine: Optional[Engine],
    markets: List[str],
    start_date: date,
    end_date: date,
    report: Callable[[str], None] = lambda message: None,
) -> int:
    """從 Yahoo Finance 補抓歷史價格，寫入 dataset 與（可選）資料庫。

    report 用於回報逐市場進度（CLI 傳入 print）。回傳補抓總筆數。
    """
    stock_master = load_stock_master(settings.stock_master_path)
    dataset_path = settings.price_dataset_path
    existing_prices = load_price_dataset(dataset_path)

    total_fetched = 0
    for market in markets:
        market_stocks = stock_master[stock_master["market"] == market]
        if market_stocks.empty:
            report(f"⚠️  無法取得 {market} 的股票清單，跳過。")
            continue

        symbols = market_stocks["symbol"].astype(str).tolist()
        report(
            f"🔄 從 Yahoo Finance 補抓 {market} {start_date} ~ {end_date}（{len(symbols)} 支股票）..."
        )

        fetched = fetch_yahoo_historical(
            market=market,
            symbols=symbols,
            start_date=start_date,
            end_date=end_date,
        )

        if fetched.empty:
            report(f"⚠️  {market} 無資料回傳，請確認日期範圍是否為交易日。")
            continue

        # Fill names from stock master
        name_map = stock_master.set_index("symbol")["name"].to_dict()
        fetched["name"] = fetched["symbol"].map(name_map).fillna("")

        rows = len(fetched)
        total_fetched += rows
        report(f"✅ {market} 取得 {rows} 筆資料")

        existing_prices = upsert_prices(existing_prices, fetched)

        if engine:
            with Session(engine) as session:
                upsert_daily_prices(
                    session=session, prices=fetched, data_version=settings.data_version
                )
                session.commit()

    save_price_dataset(existing_prices, dataset_path)
    return total_fetched
