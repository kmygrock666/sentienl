from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import List, Optional

import pandas as pd

from sentinel.logging_utils import get_logger

logger = get_logger(__name__)


def _cache_path(
    cache_dir: Path,
    trading_date: date,
    markets: List[str],
    calc_version: str,
) -> Path:
    markets_key = "-".join(sorted(m.upper() for m in markets))
    filename = f"indicators_{trading_date.isoformat()}_{markets_key}_{calc_version}.parquet"
    return cache_dir / "indicators" / filename


def load_indicator_cache(
    cache_dir: Path,
    trading_date: date,
    markets: List[str],
    calc_version: str,
) -> Optional[pd.DataFrame]:
    path = _cache_path(cache_dir, trading_date, markets, calc_version)

    if not path.exists():
        logger.info("indicator_cache_miss", extra={"path": str(path)})
        return None

    try:
        cached = pd.read_parquet(path)
    except Exception as exc:
        logger.warning("indicator_cache_read_error", extra={"path": str(path), "error": str(exc)})
        _safe_delete(path)
        return None

    logger.info(
        "indicator_cache_hit",
        extra={"path": str(path), "rows": len(cached), "trading_date": trading_date.isoformat()},
    )
    return cached


def save_indicator_cache(
    frame: pd.DataFrame,
    cache_dir: Path,
    trading_date: date,
    markets: List[str],
    calc_version: str,
) -> None:
    path = _cache_path(cache_dir, trading_date, markets, calc_version)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(".tmp")

    try:
        frame.to_parquet(tmp_path, index=False, engine="pyarrow", compression="snappy")
        tmp_path.rename(path)
        logger.info("indicator_cache_written", extra={"path": str(path), "rows": len(frame)})
    except Exception as exc:
        logger.warning("indicator_cache_write_error", extra={"path": str(path), "error": str(exc)})
        _safe_delete(tmp_path)


def invalidate_indicator_cache(
    cache_dir: Path,
    trading_date: Optional[date] = None,
) -> int:
    indicators_dir = cache_dir / "indicators"
    if not indicators_dir.exists():
        return 0

    pattern = f"indicators_{trading_date.isoformat()}_*" if trading_date else "indicators_*.parquet"
    deleted = 0
    for p in indicators_dir.glob(pattern):
        _safe_delete(p)
        deleted += 1

    logger.info("indicator_cache_invalidated", extra={"deleted": deleted})
    return deleted


def _safe_delete(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except Exception as exc:
        logger.warning("indicator_cache_delete_error", extra={"path": str(path), "error": str(exc)})
