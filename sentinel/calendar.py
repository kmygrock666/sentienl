from __future__ import annotations

from datetime import date
import json
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Set

import pandas as pd

from sentinel.providers import normalize_market_name
from sentinel.utils import daterange


def is_weekend(calendar_date: date) -> bool:
    return calendar_date.weekday() >= 5


def is_default_trading_day(calendar_date: date) -> bool:
    return not is_weekend(calendar_date)


def build_trading_calendar(
    start_date: date,
    end_date: date,
    markets: Iterable[str],
    observed_dates: Optional[Dict[str, Set[date]]] = None,
    official_overrides: Optional[pd.DataFrame] = None,
) -> pd.DataFrame:
    observed_dates = observed_dates or {}
    official_lookup = {}
    use_official = official_overrides is not None and not official_overrides.empty
    if use_official:
        for row in official_overrides.to_dict(orient="records"):
            official_lookup[(row["exchange"], row["calendar_date"])] = (
                bool(row["is_trading_day"]),
                row["reason"],
            )
    records: List[dict] = []

    for market in markets:
        exchange = normalize_market_name(market)
        market_observed = observed_dates.get(exchange, set())
        for calendar_date in daterange(start_date, end_date):
            official_record = official_lookup.get((exchange, calendar_date))
            if official_record is not None:
                is_trading_day, reason = official_record
            elif is_weekend(calendar_date):
                is_trading_day = False
                reason = "weekend"
            elif use_official:
                is_trading_day = True
                reason = None
            elif calendar_date in market_observed:
                is_trading_day = True
                reason = None
            else:
                is_trading_day = False
                reason = "no_data_from_source"

            records.append(
                {
                    "exchange": exchange,
                    "calendar_date": calendar_date,
                    "is_trading_day": is_trading_day,
                    "reason": reason,
                }
            )

    return pd.DataFrame.from_records(
        records,
        columns=["exchange", "calendar_date", "is_trading_day", "reason"],
    )


def filter_trading_dates(
    exchange: str,
    start_date: date,
    end_date: date,
    official_overrides: Optional[pd.DataFrame] = None,
) -> Set[date]:
    normalized_exchange = normalize_market_name(exchange)
    official_lookup = {}
    if official_overrides is not None and not official_overrides.empty:
        market_frame = official_overrides[official_overrides["exchange"] == normalized_exchange]
        official_lookup = {
            row["calendar_date"]: bool(row["is_trading_day"])
            for row in market_frame.to_dict(orient="records")
        }

    trading_dates = set()
    for calendar_date in daterange(start_date, end_date):
        if calendar_date in official_lookup:
            if official_lookup[calendar_date]:
                trading_dates.add(calendar_date)
            continue

        if is_default_trading_day(calendar_date):
            trading_dates.add(calendar_date)

    return trading_dates


def save_trading_calendar(
    trading_calendar: pd.DataFrame,
    output_dir: Path,
    start_date: date,
    end_date: date,
) -> Dict[str, Path]:
    output_path = output_dir / "trading_calendar"
    output_path.mkdir(parents=True, exist_ok=True)

    filename_prefix = "{0}_{1}".format(start_date.isoformat(), end_date.isoformat())
    csv_path = output_path / "{0}.csv".format(filename_prefix)
    json_path = output_path / "{0}.json".format(filename_prefix)

    export_frame = trading_calendar.copy()
    if not export_frame.empty and "calendar_date" in export_frame.columns:
        export_frame["calendar_date"] = pd.to_datetime(export_frame["calendar_date"]).dt.strftime("%Y-%m-%d")

    export_frame.to_csv(csv_path, index=False, encoding="utf-8")
    json_path.write_text(
        json.dumps(export_frame.to_dict(orient="records"), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    return {"csv": csv_path, "json": json_path}
