from __future__ import annotations

from datetime import date

import pandas as pd
from sqlalchemy import inspect
from sqlalchemy.orm import Session

from sentinel.domain.models import (
    DailyPrice,
    DataQuarantine,
    JobRun,
    ScanResult,
    Stock,
    Strategy,
    TechnicalIndicator,
    TradingCalendar,
)
from sentinel.services.pipeline import compute_indicators, scan_strategy
from sentinel.storage.engine import create_db_engine, create_schema
from sentinel.storage.persistence import finish_job_run, persist_pipeline_results, start_job_run


def test_create_schema_builds_core_tables(tmp_path) -> None:
    database_path = tmp_path / "test.db"
    engine = create_db_engine(f"sqlite:///{database_path}")

    create_schema(engine)

    tables = set(inspect(engine).get_table_names())
    assert "daily_prices" in tables
    assert "scan_results" in tables
    assert "trading_calendar" in tables


def test_persist_pipeline_results_writes_core_records(tmp_path) -> None:
    database_path = tmp_path / "persist.db"
    engine = create_db_engine(f"sqlite:///{database_path}")
    create_schema(engine)

    prices = pd.DataFrame(
        [
            {
                "symbol": "2330",
                "name": "TSMC",
                "market": "TWSE",
                "trading_date": date(2026, 1, 24),
                "open": 120.0,
                "high": 121.0,
                "low": 119.0,
                "close": 120.0,
                "volume": 1000,
                "turnover": 100000,
                "source": "fixture",
            },
            {
                "symbol": "2330",
                "name": "TSMC",
                "market": "TWSE",
                "trading_date": date(2026, 1, 25),
                "open": 124.0,
                "high": 125.0,
                "low": 123.0,
                "close": 124.0,
                "volume": 1200,
                "turnover": 120000,
                "source": "fixture",
            },
        ]
    )
    historical = pd.concat([_build_history(23), prices], ignore_index=True)
    indicators = compute_indicators(historical)
    scan_results = scan_strategy(indicators, trading_date=date(2026, 1, 25))
    trading_calendar = pd.DataFrame(
        [
            {
                "exchange": "TWSE",
                "calendar_date": date(2026, 1, 24),
                "is_trading_day": True,
                "reason": None,
            },
            {
                "exchange": "TWSE",
                "calendar_date": date(2026, 1, 25),
                "is_trading_day": False,
                "reason": "weekend",
            },
        ]
    )

    start_job_run(engine, run_id="run-1")
    counts = persist_pipeline_results(
        engine=engine,
        prices=prices,
        indicators=indicators,
        scan_results=scan_results,
        trading_calendar=trading_calendar,
        data_quarantine=None,
        run_id="run-1",
        trading_date=date(2026, 1, 25),
        data_version="v1",
    )
    finish_job_run(engine, run_id="run-1", status="success", rows_in=2, rows_out=1)

    assert counts["stocks"] == 1
    assert counts["daily_prices"] == 2
    assert counts["scan_results"] == 1
    assert counts["trading_calendar"] == 2

    with Session(engine) as session:
        assert session.query(Stock).count() == 1
        assert session.query(DailyPrice).count() == 2
        assert session.query(TechnicalIndicator).count() >= 4
        assert session.query(Strategy).count() >= 1
        assert session.query(ScanResult).count() == 1
        assert session.query(TradingCalendar).count() == 2
        assert session.query(DataQuarantine).count() == 0
        job_run = session.query(JobRun).filter_by(run_id="run-1").one()
        assert job_run.status == "success"
        assert job_run.rows_in == 2
        assert job_run.rows_out == 1


def test_persist_pipeline_results_writes_quarantine_rows(tmp_path) -> None:
    database_path = tmp_path / "quarantine.db"
    engine = create_db_engine(f"sqlite:///{database_path}")
    create_schema(engine)

    trading_calendar = pd.DataFrame(
        [
            {
                "exchange": "TWSE",
                "calendar_date": date(2026, 1, 22),
                "is_trading_day": True,
                "reason": None,
            },
        ]
    )
    quarantined_rows = pd.DataFrame(
        [
            {
                "symbol": "2330",
                "name": "TSMC",
                "market": "TWSE",
                "trading_date": date(2026, 1, 22),
                "open": 100.0,
                "high": 99.0,
                "low": 98.0,
                "close": 101.0,
                "volume": 1000,
                "turnover": 100000,
                "source": "fixture",
                "violations": ["high_gte_max_open_close"],
                "violated_rule": "validity",
            }
        ]
    )

    counts = persist_pipeline_results(
        engine=engine,
        prices=pd.DataFrame(
            columns=[
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
        ),
        indicators=pd.DataFrame(),
        scan_results=pd.DataFrame(),
        trading_calendar=trading_calendar,
        data_quarantine=quarantined_rows,
        run_id="run-quarantine",
        trading_date=date(2026, 1, 22),
        data_version="v1",
    )

    assert counts["data_quarantine"] == 1

    with Session(engine) as session:
        row = session.query(DataQuarantine).one()
        assert row.source_table == "daily_prices"
        assert row.violated_rule == "validity"
        assert row.raw_payload_json["violations"] == ["high_gte_max_open_close"]


def test_persist_pipeline_results_keeps_same_symbol_across_markets(tmp_path) -> None:
    database_path = tmp_path / "cross_market.db"
    engine = create_db_engine(f"sqlite:///{database_path}")
    create_schema(engine)

    prices = pd.DataFrame(
        [
            {
                "symbol": "6805",
                "name": "富世達",
                "market": "TWSE",
                "trading_date": date(2026, 3, 6),
                "open": 100.0,
                "high": 101.0,
                "low": 99.0,
                "close": 100.5,
                "volume": 1000,
                "turnover": 100000,
                "source": "fixture",
            },
            {
                "symbol": "6805",
                "name": "峰源-KY",
                "market": "TPEX",
                "trading_date": date(2026, 3, 6),
                "open": 50.0,
                "high": 51.0,
                "low": 49.0,
                "close": 50.5,
                "volume": 800,
                "turnover": 40000,
                "source": "fixture",
            },
        ]
    )
    history_rows = []
    for offset in range(23):
        history_rows.append(
            {
                "symbol": "6805",
                "name": "富世達",
                "market": "TWSE",
                "trading_date": date(2026, 2, 1 + offset),
                "open": 70.0 + offset,
                "high": 71.0 + offset,
                "low": 69.0 + offset,
                "close": 70.5 + offset,
                "volume": 500 + offset,
                "turnover": 50000 + offset,
                "source": "fixture-history",
            }
        )
    indicators = compute_indicators(
        pd.concat([pd.DataFrame(history_rows), prices], ignore_index=True)
    )
    scan_results = pd.DataFrame(
        [
            {
                "market": "TWSE",
                "symbol": "6805",
                "trading_date": date(2026, 3, 6),
                "strategy_id": "fixture_strategy",
                "score": 1.0,
                "signals_json": {"passed": True},
            },
            {
                "market": "TPEX",
                "symbol": "6805",
                "trading_date": date(2026, 3, 6),
                "strategy_id": "fixture_strategy",
                "score": 1.0,
                "signals_json": {"passed": True},
            },
        ]
    )

    counts = persist_pipeline_results(
        engine=engine,
        prices=prices,
        indicators=indicators,
        scan_results=scan_results,
        trading_calendar=pd.DataFrame(),
        data_quarantine=None,
        run_id="run-cross-market",
        trading_date=date(2026, 3, 6),
        data_version="v1",
        strategy_definitions=[
            {
                "strategy_id": "fixture_strategy",
                "name": "Fixture Strategy",
                "version": "1.0.0",
                "params_json": {},
                "description": "fixture",
                "is_active": True,
            }
        ],
    )

    assert counts["stocks"] == 2
    assert counts["daily_prices"] == 2
    assert counts["scan_results"] == 2

    with Session(engine) as session:
        assert session.query(Stock).count() == 2
        assert session.query(DailyPrice).count() == 2
        assert session.query(ScanResult).count() == 2
        assert (
            session.query(TechnicalIndicator).filter(TechnicalIndicator.symbol == "6805").count()
            >= 2
        )


def test_create_schema_migrates_legacy_marketless_sqlite_tables(tmp_path) -> None:
    database_path = tmp_path / "legacy.db"
    engine = create_db_engine(f"sqlite:///{database_path}")

    with engine.begin() as connection:
        connection.exec_driver_sql(
            """
            CREATE TABLE stocks (
                symbol VARCHAR(16) PRIMARY KEY,
                name VARCHAR(128),
                market VARCHAR(16) NOT NULL,
                industry VARCHAR(128),
                list_status VARCHAR(32) NOT NULL,
                created_at DATETIME NOT NULL,
                updated_at DATETIME NOT NULL
            )
            """
        )
        connection.exec_driver_sql(
            """
            CREATE TABLE daily_prices (
                symbol VARCHAR(16) NOT NULL,
                trading_date DATE NOT NULL,
                open NUMERIC(18, 4) NOT NULL,
                high NUMERIC(18, 4) NOT NULL,
                low NUMERIC(18, 4) NOT NULL,
                close NUMERIC(18, 4) NOT NULL,
                volume INTEGER NOT NULL,
                turnover NUMERIC(20, 0),
                adjusted_close NUMERIC(18, 4),
                data_version VARCHAR(64),
                updated_at DATETIME NOT NULL,
                PRIMARY KEY (symbol, trading_date)
            )
            """
        )
        connection.exec_driver_sql(
            """
            INSERT INTO stocks (symbol, name, market, industry, list_status, created_at, updated_at)
            VALUES ('2330', '台積電', 'TWSE', '半導體業', 'active', '2026-03-08 00:00:00', '2026-03-08 00:00:00')
            """
        )
        connection.exec_driver_sql(
            """
            INSERT INTO daily_prices (
                symbol, trading_date, open, high, low, close, volume, turnover, adjusted_close, data_version, updated_at
            )
            VALUES (
                '2330', '2026-03-06', 100, 101, 99, 100.5, 1000, 100000, 100.5, 'v1', '2026-03-08 00:00:00'
            )
            """
        )

    create_schema(engine)

    inspector = inspect(engine)
    assert inspector.get_pk_constraint("stocks")["constrained_columns"] == ["market", "symbol"]
    assert inspector.get_pk_constraint("daily_prices")["constrained_columns"] == [
        "market",
        "symbol",
        "trading_date",
    ]

    with Session(engine) as session:
        stock = session.query(Stock).one()
        price = session.query(DailyPrice).one()
        assert stock.market == "TWSE"
        assert price.market == "TWSE"
        assert price.symbol == "2330"

    with engine.begin() as connection:
        connection.exec_driver_sql(
            """
            INSERT INTO stocks (market, symbol, name, industry, list_status, created_at, updated_at)
            VALUES ('TPEX', '2330', '測試股', NULL, 'active', '2026-03-08 00:00:00', '2026-03-08 00:00:00')
            """
        )


def test_upsert_daily_prices_none_turnover_persists_as_null(tmp_path) -> None:
    database_path = tmp_path / "turnover_null.db"
    engine = create_db_engine(f"sqlite:///{database_path}")
    create_schema(engine)

    from sentinel.storage.persistence import upsert_daily_prices

    prices = pd.DataFrame(
        [
            {
                "symbol": "0050",
                "name": "元大台灣50",
                "market": "TWSE",
                "trading_date": date(2026, 1, 10),
                "open": 180.0,
                "high": 181.0,
                "low": 179.0,
                "close": 180.5,
                "volume": 5000,
                "turnover": None,
            }
        ]
    )

    with Session(engine) as session:
        count = upsert_daily_prices(session, prices, data_version="v1")
        session.commit()

    assert count == 1

    with Session(engine) as session:
        row = session.query(DailyPrice).one()
        assert row.turnover is None


def test_upsert_technical_indicators_excludes_rows_with_no_matching_price_key(tmp_path) -> None:
    database_path = tmp_path / "indicator_key_filter.db"
    engine = create_db_engine(f"sqlite:///{database_path}")
    create_schema(engine)

    from sentinel.storage.persistence import upsert_daily_prices, upsert_technical_indicators

    prices = pd.DataFrame(
        [
            {
                "symbol": "2330",
                "name": "TSMC",
                "market": "TWSE",
                "trading_date": date(2026, 2, 5),
                "open": 100.0,
                "high": 101.0,
                "low": 99.0,
                "close": 100.5,
                "volume": 1000,
                "turnover": 100000,
            }
        ]
    )

    # indicators: one row whose key matches prices, one whose key does NOT
    indicators = pd.DataFrame(
        [
            {
                "market": "TWSE",
                "symbol": "2330",
                "trading_date": date(2026, 2, 5),
                "ma5": 99.0,
            },
            {
                "market": "TWSE",
                "symbol": "9999",  # no matching price row
                "trading_date": date(2026, 2, 5),
                "ma5": 55.0,
            },
        ]
    )

    with Session(engine) as session:
        upsert_daily_prices(session, prices, data_version="v1")
        count = upsert_technical_indicators(session, indicators, prices)
        session.commit()

    # only the matching row's ma5 column should have been written
    assert count == 1


def _build_history(days: int) -> pd.DataFrame:
    records = []
    for offset in range(days):
        records.append(
            {
                "symbol": "2330",
                "name": "TSMC",
                "market": "TWSE",
                "trading_date": date(2026, 1, 1 + offset),
                "open": 100.0 + offset,
                "high": 101.0 + offset,
                "low": 99.0 + offset,
                "close": 100.0 + offset,
                "volume": 1000 + offset,
                "turnover": 100000 + offset,
                "source": "fixture",
            }
        )
    return pd.DataFrame(records)
