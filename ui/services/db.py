from __future__ import annotations

import streamlit as st
from sqlalchemy import inspect as sa_inspect
from sqlalchemy import text
from sqlalchemy.engine import Engine

from sentinel.config import Settings
from sentinel.storage.engine import create_db_engine

_REQUIRED_TABLES = {"stocks", "daily_prices", "scan_results"}


def _reset_stale_jobs(engine: Engine) -> None:
    """將 Streamlit 重啟前殘留的 running 狀態 job_runs 標記為 failed。

    進程被強制中斷（重開機、docker restart）時 finish_job_run() 來不及執行，
    下次啟動時由此函式修復，避免 UI 顯示不存在的「執行中」任務。
    """
    with engine.begin() as conn:
        conn.execute(
            text(
                """
            UPDATE job_runs
            SET status      = 'failed',
                end_time    = start_time,
                error_summary = 'Interrupted: process killed before completion'
            WHERE status = 'running'
        """
            )
        )


@st.cache_resource
def get_engine() -> Engine:
    settings = Settings()
    if not settings.database_url:
        raise RuntimeError("TS_DATABASE_URL 未設定，請在 .env 中加入資料庫連線字串")
    engine = create_db_engine(settings.database_url)
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception as e:
        raise RuntimeError(f"資料庫連線失敗：{e}") from e
    missing = _REQUIRED_TABLES - set(sa_inspect(engine).get_table_names())
    if missing:
        raise RuntimeError(
            f"資料庫 Schema 尚未初始化（缺少資料表：{', '.join(sorted(missing))}），"
            "請前往 Data Sync 頁面執行「初始化資料庫」"
        )
    _reset_stale_jobs(engine)
    return engine
