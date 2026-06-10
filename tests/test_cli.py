from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
from sqlalchemy.orm import Session

from sentinel.cli import main
from sentinel.db import create_db_engine
from sentinel.models import (
    DailyPrice,
    DataQuarantine,
    ScanResult,
    Stock,
    TechnicalIndicator,
    TradingCalendar,
)


def test_sync_calendar_fixture_mode_writes_outputs_and_db(tmp_path, monkeypatch) -> None:
    data_dir = tmp_path / "data"
    output_dir = tmp_path / "outputs"
    fixture_target_dir = data_dir / "raw" / "fixtures" / "trading_calendar"
    fixture_target_dir.mkdir(parents=True, exist_ok=True)

    fixture_source_dir = Path(__file__).parent / "fixtures" / "trading_calendar"
    for fixture_name in ("twse_holiday_2026.html", "tpex_holiday_2026.html"):
        (fixture_target_dir / fixture_name).write_text(
            (fixture_source_dir / fixture_name).read_text(encoding="utf-8"),
            encoding="utf-8",
        )

    database_path = tmp_path / "calendar.db"
    database_url = "sqlite:///{0}".format(database_path)

    monkeypatch.setenv("TS_DATA_DIR", str(data_dir))
    monkeypatch.setenv("TS_OUTPUT_DIR", str(output_dir))
    monkeypatch.setenv("TS_DATABASE_URL", database_url)

    assert main(["init-db", "--database-url", database_url]) == 0

    assert (
        main(
            [
                "sync-calendar",
                "--market",
                "TWSE",
                "--market",
                "TPEX",
                "--source-mode",
                "fixture",
                "--start-date",
                "2026-01-22",
                "--end-date",
                "2026-01-27",
            ]
        )
        == 0
    )

    csv_path = output_dir / "trading_calendar" / "2026-01-22_2026-01-27.csv"
    json_path = output_dir / "trading_calendar" / "2026-01-22_2026-01-27.json"
    assert csv_path.exists()
    assert json_path.exists()

    engine = create_db_engine(database_url)
    with Session(engine) as session:
        rows = (
            session.query(TradingCalendar)
            .order_by(TradingCalendar.exchange, TradingCalendar.calendar_date)
            .all()
        )
        assert len(rows) == 12
        twse_rows = [row for row in rows if row.exchange == "TWSE"]
        tpex_rows = [row for row in rows if row.exchange == "TPEX"]
        assert len(twse_rows) == 6
        assert len(tpex_rows) == 6
        assert any(row.reason and "結算交割" in row.reason for row in twse_rows)
        assert any(row.reason == "weekend" for row in tpex_rows)


def test_sync_stocks_fixture_mode_writes_dataset_and_db(tmp_path, monkeypatch) -> None:
    data_dir = tmp_path / "data"
    output_dir = tmp_path / "outputs"
    fixture_target_dir = data_dir / "raw" / "fixtures" / "stocks"
    fixture_target_dir.mkdir(parents=True, exist_ok=True)

    fixture_source_dir = Path(__file__).parent / "fixtures" / "stocks"
    for fixture_name in ("twse_stocks.csv", "tpex_stocks.csv"):
        (fixture_target_dir / fixture_name).write_text(
            (fixture_source_dir / fixture_name).read_text(encoding="utf-8"),
            encoding="utf-8",
        )

    database_path = tmp_path / "stocks.db"
    database_url = "sqlite:///{0}".format(database_path)
    monkeypatch.setenv("TS_DATA_DIR", str(data_dir))
    monkeypatch.setenv("TS_OUTPUT_DIR", str(output_dir))
    monkeypatch.setenv("TS_DATABASE_URL", database_url)

    assert main(["init-db", "--database-url", database_url]) == 0
    assert (
        main(
            [
                "sync-stocks",
                "--market",
                "TWSE",
                "--market",
                "TPEX",
                "--source-mode",
                "fixture",
                "--database-url",
                database_url,
            ]
        )
        == 0
    )

    stock_master_path = data_dir / "processed" / "stocks.csv"
    diagnostics_path = output_dir / "stock_master" / "sync_diagnostics.json"
    assert stock_master_path.exists()
    assert diagnostics_path.exists()
    stock_master = pd.read_csv(stock_master_path)
    assert len(stock_master.index) == 3
    diagnostics = json.loads(diagnostics_path.read_text(encoding="utf-8"))
    assert diagnostics["diagnostics"][0]["attempts"][0]["transport"] == "fixture"
    assert diagnostics["diagnostics"][0]["attempts"][0]["status"] == "success"

    engine = create_db_engine(database_url)
    with Session(engine) as session:
        rows = session.query(TradingCalendar).count()
        assert rows == 0
        assert session.query(Stock).count() == 3


def test_run_fixture_mode_writes_scan_outputs_and_db(tmp_path, monkeypatch) -> None:
    data_dir = tmp_path / "data"
    output_dir = tmp_path / "outputs"
    calendar_fixture_dir = data_dir / "raw" / "fixtures" / "trading_calendar"
    price_fixture_dir = data_dir / "raw" / "fixtures" / "prices"
    stock_fixture_dir = data_dir / "raw" / "fixtures" / "stocks"
    calendar_fixture_dir.mkdir(parents=True, exist_ok=True)
    price_fixture_dir.mkdir(parents=True, exist_ok=True)
    stock_fixture_dir.mkdir(parents=True, exist_ok=True)

    fixture_root = Path(__file__).parent / "fixtures"
    for fixture_name in ("twse_holiday_2026.html",):
        (calendar_fixture_dir / fixture_name).write_text(
            (fixture_root / "trading_calendar" / fixture_name).read_text(encoding="utf-8"),
            encoding="utf-8",
        )
    for fixture_name in ("twse_daily_20260122.csv",):
        (price_fixture_dir / fixture_name).write_text(
            (fixture_root / "prices" / fixture_name).read_text(encoding="utf-8"),
            encoding="utf-8",
        )
    for fixture_name in ("twse_stocks.csv",):
        (stock_fixture_dir / fixture_name).write_text(
            (fixture_root / "stocks" / fixture_name).read_text(encoding="utf-8"),
            encoding="utf-8",
        )

    processed_dir = data_dir / "processed"
    processed_dir.mkdir(parents=True, exist_ok=True)
    historical_rows = []
    for offset in range(24):
        historical_rows.append(
            {
                "symbol": "2330",
                "name": "台積電",
                "market": "TWSE",
                "trading_date": (
                    "2025-12-{0:02d}".format(offset + 1) if offset < 31 else "2026-01-01"
                ),
                "open": 580.0 + offset,
                "high": 581.0 + offset,
                "low": 579.0 + offset,
                "close": 580.0 + offset,
                "volume": 1000 + offset,
                "turnover": 100000 + offset,
                "source": "fixture-history",
            }
        )
    pd.DataFrame(historical_rows).to_csv(
        processed_dir / "daily_prices.csv", index=False, encoding="utf-8"
    )

    database_path = tmp_path / "run.db"
    database_url = "sqlite:///{0}".format(database_path)
    monkeypatch.setenv("TS_DATA_DIR", str(data_dir))
    monkeypatch.setenv("TS_OUTPUT_DIR", str(output_dir))
    monkeypatch.setenv("TS_DATABASE_URL", database_url)

    assert main(["init-db", "--database-url", database_url]) == 0
    assert (
        main(
            [
                "sync-stocks",
                "--market",
                "TWSE",
                "--source-mode",
                "fixture",
                "--database-url",
                database_url,
            ]
        )
        == 0
    )
    assert (
        main(
            [
                "run",
                "--market",
                "TWSE",
                "--calendar-source-mode",
                "fixture",
                "--price-source-mode",
                "fixture",
                "--start-date",
                "2026-01-22",
                "--end-date",
                "2026-01-22",
                "--trading-date",
                "2026-01-22",
                # Use a non-existent path so load_strategy_definitions falls back to
                # DEFAULT_STRATEGY_DEFINITIONS (min_history_days=25), which can fire
                # on the 25-row fixture dataset.
                "--strategy-path",
                str(tmp_path / "no_strategies.json"),
            ]
        )
        == 0
    )

    run_output_dir = output_dir / "2026-01-22"
    assert (run_output_dir / "scan_results.csv").exists()
    assert (run_output_dir / "scan_results.json").exists()
    assert (run_output_dir / "metadata.json").exists()
    metadata = json.loads((run_output_dir / "metadata.json").read_text(encoding="utf-8"))
    assert metadata["completeness"]["basis"] == "active_stocks_master"
    assert metadata["completeness"]["expected_rows"] == 2
    assert metadata["completeness"]["actual_rows"] == 1
    assert metadata["completeness"]["quarantined_rows"] == 0
    assert metadata["completeness"]["completeness_pct"] == 0.5

    engine = create_db_engine(database_url)
    with Session(engine) as session:
        assert session.query(DailyPrice).count() == 1
        assert session.query(TechnicalIndicator).count() >= 4
        assert session.query(ScanResult).count() >= 1


def test_run_quarantines_invalid_daily_prices(tmp_path, monkeypatch) -> None:
    data_dir = tmp_path / "data"
    output_dir = tmp_path / "outputs"
    calendar_fixture_dir = data_dir / "raw" / "fixtures" / "trading_calendar"
    price_fixture_dir = data_dir / "raw" / "fixtures" / "prices"
    stock_fixture_dir = data_dir / "raw" / "fixtures" / "stocks"
    calendar_fixture_dir.mkdir(parents=True, exist_ok=True)
    price_fixture_dir.mkdir(parents=True, exist_ok=True)
    stock_fixture_dir.mkdir(parents=True, exist_ok=True)

    fixture_root = Path(__file__).parent / "fixtures"
    (calendar_fixture_dir / "twse_holiday_2026.html").write_text(
        (fixture_root / "trading_calendar" / "twse_holiday_2026.html").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    (price_fixture_dir / "twse_daily_20260122.csv").write_text(
        (fixture_root / "prices" / "twse_daily_invalid_20260122.csv").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    (stock_fixture_dir / "twse_stocks.csv").write_text(
        (fixture_root / "stocks" / "twse_stocks.csv").read_text(encoding="utf-8"),
        encoding="utf-8",
    )

    database_path = tmp_path / "quarantine.db"
    database_url = "sqlite:///{0}".format(database_path)
    monkeypatch.setenv("TS_DATA_DIR", str(data_dir))
    monkeypatch.setenv("TS_OUTPUT_DIR", str(output_dir))
    monkeypatch.setenv("TS_DATABASE_URL", database_url)

    assert main(["init-db", "--database-url", database_url]) == 0
    assert (
        main(
            [
                "sync-stocks",
                "--market",
                "TWSE",
                "--source-mode",
                "fixture",
                "--database-url",
                database_url,
            ]
        )
        == 0
    )
    assert (
        main(
            [
                "run",
                "--market",
                "TWSE",
                "--calendar-source-mode",
                "fixture",
                "--price-source-mode",
                "fixture",
                "--start-date",
                "2026-01-22",
                "--end-date",
                "2026-01-22",
                "--trading-date",
                "2026-01-22",
            ]
        )
        == 0
    )

    metadata = json.loads((output_dir / "2026-01-22" / "metadata.json").read_text(encoding="utf-8"))
    assert metadata["completeness"]["basis"] == "active_stocks_master"
    assert metadata["completeness"]["expected_rows"] == 2
    assert metadata["completeness"]["actual_rows"] == 0
    assert metadata["completeness"]["quarantined_rows"] == 1
    assert metadata["completeness"]["completeness_pct"] == 0.0

    engine = create_db_engine(database_url)
    with Session(engine) as session:
        assert session.query(DailyPrice).count() == 0
        assert session.query(TechnicalIndicator).count() == 0
        assert session.query(ScanResult).count() == 0
        quarantine_row = session.query(DataQuarantine).one()
        assert quarantine_row.source_table == "daily_prices"
        assert quarantine_row.violated_rule == "validity"
        assert quarantine_row.raw_payload_json["violations"] == ["high_gte_max_open_close"]


def test_backtest_writes_report_and_trades(tmp_path, monkeypatch) -> None:
    data_dir = tmp_path / "data"
    output_dir = tmp_path / "outputs"
    processed_dir = data_dir / "processed"
    processed_dir.mkdir(parents=True, exist_ok=True)

    historical_rows = []
    for offset in range(50):
        month = "01" if offset < 31 else "02"
        day = offset + 1 if offset < 31 else offset - 30
        historical_rows.append(
            {
                "symbol": "2330",
                "name": "台積電",
                "market": "TWSE",
                "trading_date": "2026-{0}-{1:02d}".format(month, day),
                "open": 100.0 + offset,
                "high": 101.0 + offset,
                "low": 99.0 + offset,
                "close": 100.5 + offset,
                "volume": 1000 + offset,
                "turnover": 100000 + offset,
                "source": "fixture-history",
            }
        )
    pd.DataFrame(historical_rows).to_csv(
        processed_dir / "daily_prices.csv", index=False, encoding="utf-8"
    )

    database_path = tmp_path / "backtest.db"
    database_url = "sqlite:///{0}".format(database_path)
    monkeypatch.setenv("TS_DATA_DIR", str(data_dir))
    monkeypatch.setenv("TS_OUTPUT_DIR", str(output_dir))
    monkeypatch.setenv("TS_DATABASE_URL", database_url)

    assert main(["init-db", "--database-url", database_url]) == 0
    assert (
        main(
            [
                "backtest",
                "--start-date",
                "2026-01-25",
                "--end-date",
                "2026-02-15",
                "--market",
                "TWSE",
                "--benchmark-symbol",
                "2330",
            ]
        )
        == 0
    )

    backtest_output_dir = output_dir / "backtests" / "2026-01-25_2026-02-15"
    assert (backtest_output_dir / "report.csv").exists()
    assert (backtest_output_dir / "trades.csv").exists()
    assert (backtest_output_dir / "metadata.json").exists()
