from __future__ import annotations

import argparse

from sqlalchemy.engine import Engine

from sentinel.config import Settings
from sentinel.db import create_db_engine, create_schema

MARKET_LABELS = {"TWSE": "上市", "TPEX": "上櫃"}


def require_database_url(
    args: argparse.Namespace, settings: Settings, parser: argparse.ArgumentParser
) -> str:
    """回傳 --database-url 或環境設定；兩者皆缺時以 parser.error 終止。"""
    database_url = args.database_url or settings.database_url
    if not database_url:
        parser.error("--database-url is required or set TS_DATABASE_URL in the environment")
    return database_url


def create_engine_with_schema(database_url: str) -> Engine:
    engine = create_db_engine(database_url)
    create_schema(engine)
    return engine
