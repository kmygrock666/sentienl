from __future__ import annotations

import pandas as pd
from sqlalchemy import func
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from sentinel.models import DataQuarantine


def get_quarantine_summary(engine: Engine) -> dict:
    with Session(engine) as s:
        total = s.query(func.count(DataQuarantine.quarantine_id)).scalar() or 0
        pending = (
            s.query(func.count(DataQuarantine.quarantine_id))
            .filter(DataQuarantine.resolution == "pending")
            .scalar()
            or 0
        )
        recent = s.query(DataQuarantine).order_by(DataQuarantine.detected_at.desc()).limit(10).all()
    recent_df = (
        pd.DataFrame(
            [
                {
                    "detected_at": r.detected_at,
                    "source_table": r.source_table,
                    "violated_rule": r.violated_rule,
                    "resolution": r.resolution,
                }
                for r in recent
            ]
        )
        if recent
        else pd.DataFrame()
    )
    return {"total": total, "pending": pending, "recent": recent_df}
