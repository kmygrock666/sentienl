from __future__ import annotations

from pathlib import Path

from sqlalchemy import create_engine, inspect
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker

from sentinel.models import Base


def create_db_engine(database_url: str) -> Engine:
    _ensure_sqlite_parent_dir(database_url)
    if database_url.startswith("sqlite"):
        # 增加 timeout 與設定連線事件
        from sqlalchemy import event
        from sqlalchemy.pool import QueuePool

        engine = create_engine(database_url, connect_args={"timeout": 30.0}, future=True)

        @event.listens_for(engine, "connect")
        def set_sqlite_pragma(dbapi_connection, connection_record):
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA synchronous=NORMAL")
            cursor.close()

        return engine
    return create_engine(database_url, future=True)


def create_session_factory(engine: Engine) -> sessionmaker:
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


def create_schema(engine: Engine) -> None:
    Base.metadata.create_all(bind=engine)
    _migrate_legacy_sqlite_schema(engine)


def _ensure_sqlite_parent_dir(database_url: str) -> None:
    if not database_url.startswith("sqlite:///"):
        return

    raw_path = database_url.removeprefix("sqlite:///")
    if not raw_path or raw_path == ":memory:":
        return

    db_path = Path(raw_path).expanduser()
    db_path.parent.mkdir(parents=True, exist_ok=True)


def _migrate_legacy_sqlite_schema(engine: Engine) -> None:
    if engine.dialect.name != "sqlite":
        return

    inspector = inspect(engine)
    target_pk_columns = {
        "stocks": ["market", "symbol"],
        "daily_prices": ["market", "symbol", "trading_date"],
        "technical_indicators": [
            "market",
            "symbol",
            "trading_date",
            "indicator_name",
            "params_hash",
            "calc_version",
        ],
        "scan_results": ["run_id", "market", "symbol", "strategy_id"],
    }
    table_shapes = {}
    legacy_tables = []
    for table_name, expected_pk in target_pk_columns.items():
        if table_name not in inspector.get_table_names():
            continue
        columns = [column["name"] for column in inspector.get_columns(table_name)]
        pk_columns = inspector.get_pk_constraint(table_name).get("constrained_columns") or []
        table_shapes[table_name] = {"columns": columns, "pk_columns": pk_columns}
        if columns != [] and (("market" not in columns) or (pk_columns != expected_pk)):
            legacy_tables.append(table_name)
    if not legacy_tables:
        return

    with engine.begin() as connection:
        for table_name in legacy_tables:
            connection.exec_driver_sql("ALTER TABLE {0} RENAME TO {0}__legacy".format(table_name))

    Base.metadata.create_all(bind=engine)

    copy_sql = {
        "stocks": """
            INSERT OR REPLACE INTO stocks (
                market, symbol, name, industry, list_status, created_at, updated_at
            )
            SELECT
                COALESCE(NULLIF(TRIM(market), ''), 'UNKNOWN'),
                symbol,
                name,
                industry,
                COALESCE(NULLIF(TRIM(list_status), ''), 'active'),
                created_at,
                updated_at
            FROM stocks__legacy
        """,
        "daily_prices_with_market": """
            INSERT OR REPLACE INTO daily_prices (
                market, symbol, trading_date, open, high, low, close, volume,
                turnover, adjusted_close, data_version, updated_at
            )
            SELECT
                COALESCE(NULLIF(TRIM(dp.market), ''), 'UNKNOWN'),
                dp.symbol,
                dp.trading_date,
                dp.open,
                dp.high,
                dp.low,
                dp.close,
                dp.volume,
                dp.turnover,
                dp.adjusted_close,
                dp.data_version,
                dp.updated_at
            FROM daily_prices__legacy dp
        """,
        "daily_prices_without_market": """
            INSERT OR REPLACE INTO daily_prices (
                market, symbol, trading_date, open, high, low, close, volume,
                turnover, adjusted_close, data_version, updated_at
            )
            SELECT
                COALESCE(NULLIF(TRIM(s.market), ''), 'UNKNOWN'),
                dp.symbol,
                dp.trading_date,
                dp.open,
                dp.high,
                dp.low,
                dp.close,
                dp.volume,
                dp.turnover,
                dp.adjusted_close,
                dp.data_version,
                dp.updated_at
            FROM daily_prices__legacy dp
            LEFT JOIN stocks s
              ON s.symbol = dp.symbol
        """,
        "technical_indicators_with_market": """
            INSERT OR REPLACE INTO technical_indicators (
                market, symbol, trading_date, indicator_name, params_hash,
                calc_version, value, source_field, updated_at
            )
            SELECT
                COALESCE(NULLIF(TRIM(ti.market), ''), 'UNKNOWN'),
                ti.symbol,
                ti.trading_date,
                ti.indicator_name,
                ti.params_hash,
                ti.calc_version,
                ti.value,
                ti.source_field,
                ti.updated_at
            FROM technical_indicators__legacy ti
        """,
        "technical_indicators_without_market": """
            INSERT OR REPLACE INTO technical_indicators (
                market, symbol, trading_date, indicator_name, params_hash,
                calc_version, value, source_field, updated_at
            )
            SELECT
                COALESCE(NULLIF(TRIM(dp.market), ''), 'UNKNOWN'),
                ti.symbol,
                ti.trading_date,
                ti.indicator_name,
                ti.params_hash,
                ti.calc_version,
                ti.value,
                ti.source_field,
                ti.updated_at
            FROM technical_indicators__legacy ti
            LEFT JOIN daily_prices dp
              ON dp.symbol = ti.symbol
             AND dp.trading_date = ti.trading_date
        """,
        "scan_results_with_market": """
            INSERT OR REPLACE INTO scan_results (
                run_id, market, symbol, strategy_id, trading_date, score,
                signals_json, data_version, created_at
            )
            SELECT
                sr.run_id,
                COALESCE(NULLIF(TRIM(sr.market), ''), 'UNKNOWN'),
                sr.symbol,
                sr.strategy_id,
                sr.trading_date,
                sr.score,
                sr.signals_json,
                sr.data_version,
                sr.created_at
            FROM scan_results__legacy sr
        """,
        "scan_results_without_market": """
            INSERT OR REPLACE INTO scan_results (
                run_id, market, symbol, strategy_id, trading_date, score,
                signals_json, data_version, created_at
            )
            SELECT
                sr.run_id,
                COALESCE(NULLIF(TRIM(dp.market), ''), 'UNKNOWN'),
                sr.symbol,
                sr.strategy_id,
                sr.trading_date,
                sr.score,
                sr.signals_json,
                sr.data_version,
                sr.created_at
            FROM scan_results__legacy sr
            LEFT JOIN daily_prices dp
              ON dp.symbol = sr.symbol
             AND dp.trading_date = sr.trading_date
        """,
    }

    with engine.begin() as connection:
        for table_name in legacy_tables:
            columns = table_shapes[table_name]["columns"]
            if table_name == "stocks":
                statement = copy_sql["stocks"]
            elif table_name == "daily_prices":
                statement = (
                    copy_sql["daily_prices_with_market"]
                    if "market" in columns
                    else copy_sql["daily_prices_without_market"]
                )
            elif table_name == "technical_indicators":
                statement = (
                    copy_sql["technical_indicators_with_market"]
                    if "market" in columns
                    else copy_sql["technical_indicators_without_market"]
                )
            else:
                statement = (
                    copy_sql["scan_results_with_market"]
                    if "market" in columns
                    else copy_sql["scan_results_without_market"]
                )
            connection.exec_driver_sql(statement)
            connection.exec_driver_sql("DROP TABLE {0}__legacy".format(table_name))
