from __future__ import annotations

import pandas as pd
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from sentinel.models import JobRun


def get_latest_job_runs(engine: Engine, limit: int = 10) -> pd.DataFrame:
    with Session(engine) as s:
        rows = s.query(JobRun).order_by(JobRun.start_time.desc()).limit(limit).all()
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(
        [
            {
                "run_id": r.run_id,
                "job_name": r.job_name,
                "status": r.status,
                "start_time": r.start_time,
                "end_time": r.end_time,
                "rows_in": r.rows_in,
                "rows_out": r.rows_out,
                "error_summary": r.error_summary,
            }
            for r in rows
        ]
    )
