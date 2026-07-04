from __future__ import annotations

from pathlib import Path

import pandas as pd

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


def load_price_dataset(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame(columns=PRICE_COLUMNS)

    frame = pd.read_csv(path, dtype={"symbol": str})
    if frame.empty:
        return pd.DataFrame(columns=PRICE_COLUMNS)
    return _normalize_price_frame(frame)


def upsert_prices(existing: pd.DataFrame, incoming: pd.DataFrame) -> pd.DataFrame:
    if existing.empty and incoming.empty:
        return pd.DataFrame(columns=PRICE_COLUMNS)
    if existing.empty:
        merged = incoming.copy()
    elif incoming.empty:
        merged = existing.copy()
    else:
        merged = pd.concat([existing, incoming], ignore_index=True)

    merged = _normalize_price_frame(merged)
    merged = merged.drop_duplicates(subset=["symbol", "market", "trading_date"], keep="last")
    merged = merged.sort_values(["market", "symbol", "trading_date"]).reset_index(drop=True)
    return merged[PRICE_COLUMNS]


def save_price_dataset(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    export_frame = _normalize_price_frame(frame)
    export_frame.to_csv(path, index=False, encoding="utf-8")


def _normalize_price_frame(frame: pd.DataFrame) -> pd.DataFrame:
    normalized = frame.copy()
    normalized["symbol"] = _normalize_text_column(normalized["symbol"])
    normalized["name"] = _normalize_text_column(normalized["name"])
    normalized["market"] = _normalize_text_column(normalized["market"]).str.upper()
    normalized["source"] = _normalize_text_column(normalized["source"])
    normalized["trading_date"] = pd.to_datetime(normalized["trading_date"]).dt.date

    for column in ["open", "high", "low", "close", "volume", "turnover"]:
        normalized[column] = pd.to_numeric(normalized[column], errors="coerce")

    return normalized[PRICE_COLUMNS]


def _normalize_text_column(series: pd.Series) -> pd.Series:
    return series.where(series.notna(), "").astype(str).str.strip()
