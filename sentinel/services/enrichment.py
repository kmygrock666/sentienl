from __future__ import annotations

import pandas as pd
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from sentinel.datasources.institutional import enrich_with_institutional, load_institutional_frame
from sentinel.logging_utils import get_logger

_logger = get_logger(__name__)


def apply_institutional_enrichment(frame: pd.DataFrame, engine: Engine) -> pd.DataFrame:
    """以資料庫中的法人買賣超 enrich 指標 frame；失敗時記 warning 並回傳原 frame。"""
    try:
        date_col: pd.Series = frame["trading_date"]  # type: ignore[assignment]
        dates = pd.DatetimeIndex(pd.to_datetime(date_col)).date  # ndarray[date]
        with Session(engine) as session:
            flows = load_institutional_frame(session, start_date=min(dates), end_date=max(dates))
        enriched = enrich_with_institutional(frame, flows)
        _logger.info("institutional_enriched", extra={"flow_rows": len(flows.index)})
        return enriched
    except Exception as exc:  # noqa: BLE001 - enrichment 失敗不應中斷主流程
        _logger.warning("institutional_enrich_failed", extra={"error": str(exc)})
        return frame
