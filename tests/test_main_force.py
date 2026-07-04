"""主力買賣超（券商分點 Top-N）測試：compute / fetch / upsert。"""

from __future__ import annotations

from datetime import date
from typing import Any

import pandas as pd
import pytest
from sqlalchemy.orm import Session

from sentinel.config import Settings
from sentinel.datasources.main_force import (
    REPORT_COLUMNS,
    FinMindError,
    compute_main_force_daily,
    fetch_trading_daily_report,
)
from sentinel.domain.models import MainForceDaily
from sentinel.storage.engine import create_db_engine, create_schema
from sentinel.storage.persistence import upsert_main_force_daily

# ═══════════════════════════════════════════════════════════════════════════
# compute_main_force_daily（純邏輯）
# ═══════════════════════════════════════════════════════════════════════════

_COMPUTE_COLUMNS = ["trading_date", "main_buy", "main_sell", "main_net", "branch_count"]


def _report_frame(rows: list) -> pd.DataFrame:
    return pd.DataFrame(rows, columns=["date", "securities_trader_id", "buy", "sell"])


def test_compute_hand_computed_top2() -> None:
    """5 個分點 nets = +100, +50, +10, −30, −80；top_n=2。

    主力買超 = 100 + 50 = 150
    主力賣超 = (−80) + (−30) = −110
    主力買賣超 = 150 + (−110) = 40
    branch_count = 5
    """
    report = _report_frame(
        [
            ["2026-06-09", "A001", 100, 0],
            ["2026-06-09", "B002", 70, 20],
            ["2026-06-09", "C003", 15, 5],
            ["2026-06-09", "D004", 10, 40],
            ["2026-06-09", "E005", 0, 80],
        ]
    )

    out = compute_main_force_daily(report, top_n=2)

    assert list(out.columns) == _COMPUTE_COLUMNS
    assert len(out) == 1
    row = out.iloc[0]
    assert row["trading_date"] == date(2026, 6, 9)
    assert row["main_buy"] == 150
    assert row["main_sell"] == -110
    assert row["main_net"] == 40
    assert row["branch_count"] == 5


def test_compute_groups_by_date() -> None:
    """多日資料應逐日獨立計算並依日期昇冪輸出。"""
    report = _report_frame(
        [
            ["2026-06-10", "A001", 30, 0],
            ["2026-06-09", "A001", 100, 0],
            ["2026-06-09", "B002", 0, 60],
            ["2026-06-10", "B002", 0, 10],
        ]
    )

    out = compute_main_force_daily(report, top_n=15)

    assert list(out["trading_date"]) == [date(2026, 6, 9), date(2026, 6, 10)]
    d9 = out.iloc[0]
    assert (d9["main_buy"], d9["main_sell"], d9["main_net"], d9["branch_count"]) == (
        100,
        -60,
        40,
        2,
    )
    d10 = out.iloc[1]
    assert (d10["main_buy"], d10["main_sell"], d10["main_net"], d10["branch_count"]) == (
        30,
        -10,
        20,
        2,
    )


def test_compute_fewer_branches_than_top_n() -> None:
    """分點數 < top_n 時取全部，不報錯。"""
    report = _report_frame(
        [
            ["2026-06-09", "A001", 100, 0],
            ["2026-06-09", "B002", 0, 30],
        ]
    )

    out = compute_main_force_daily(report, top_n=15)

    row = out.iloc[0]
    assert row["main_buy"] == 100
    assert row["main_sell"] == -30
    assert row["main_net"] == 70
    assert row["branch_count"] == 2


def test_compute_all_negative_day() -> None:
    """全部分點皆賣超：main_buy=0、main_sell 為負總和。"""
    report = _report_frame(
        [
            ["2026-06-09", "A001", 0, 50],
            ["2026-06-09", "B002", 10, 40],
        ]
    )

    out = compute_main_force_daily(report, top_n=15)

    row = out.iloc[0]
    assert row["main_buy"] == 0
    assert row["main_sell"] == -80
    assert row["main_net"] == -80
    assert row["branch_count"] == 2


def test_compute_empty_input_returns_empty_frame_with_columns() -> None:
    out = compute_main_force_daily(pd.DataFrame(columns=REPORT_COLUMNS), top_n=15)

    assert out.empty
    assert list(out.columns) == _COMPUTE_COLUMNS


def test_compute_duplicate_branch_rows_aggregated_once() -> None:
    """同一 trader_id 在同日出現兩列時，應先合併再計入 top_n。

    A001: +100 net (row 1) + +50 net (row 2) → aggregate net = +150
    D004: −30 net
    top_n=2: main_buy=150（A001 計一次）、main_sell=−30、branch_count=2
    """
    report = _report_frame(
        [
            ["2026-06-09", "A001", 100, 0],
            ["2026-06-09", "A001", 50, 0],
            ["2026-06-09", "D004", 10, 40],
        ]
    )

    out = compute_main_force_daily(report, top_n=2)

    assert len(out) == 1
    row = out.iloc[0]
    assert row["main_buy"] == 150
    assert row["main_sell"] == -30
    assert row["main_net"] == 120
    assert row["branch_count"] == 2


# ═══════════════════════════════════════════════════════════════════════════
# fetch_trading_daily_report
# ═══════════════════════════════════════════════════════════════════════════


class _FakeResponse:
    def __init__(self, payload: dict[str, Any], status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code

    def json(self) -> dict[str, Any]:
        return self._payload


def _settings(token: str | None) -> Settings:
    return Settings(finmind_token=token, _env_file=None)


def test_fetch_missing_token_raises_actionable_error() -> None:
    with pytest.raises(FinMindError) as excinfo:
        fetch_trading_daily_report("5347", date(2026, 6, 2), date(2026, 6, 9), _settings(None))

    message = str(excinfo.value)
    assert "TS_FINMIND_TOKEN" in message
    assert "Sponsor" in message
    assert ".env" in message


def test_fetch_success_returns_rows(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    def _fake_get(url, params=None, timeout=None):
        captured["url"] = url
        captured["params"] = params
        captured["timeout"] = timeout
        return _FakeResponse(
            {
                "msg": "success",
                "status": 200,
                "data": [
                    {
                        "date": "2026-06-09",
                        "stock_id": "5347",
                        "securities_trader": "凱基",
                        "securities_trader_id": "9200",
                        "price": 123.0,
                        "buy": 50000,
                        "sell": 20000,
                    }
                ],
            }
        )

    monkeypatch.setattr("sentinel.datasources.main_force.requests.get", _fake_get)

    df = fetch_trading_daily_report(
        "5347", date(2026, 6, 2), date(2026, 6, 9), _settings("token-x")
    )

    assert len(df) == 1
    assert df.iloc[0]["securities_trader_id"] == "9200"
    assert captured["params"]["dataset"] == "TaiwanStockTradingDailyReport"
    assert captured["params"]["data_id"] == "5347"
    assert captured["params"]["start_date"] == "2026-06-02"
    assert captured["params"]["end_date"] == "2026-06-09"
    assert captured["params"]["token"] == "token-x"
    assert captured["timeout"] is not None


def test_fetch_empty_data_returns_empty_frame_with_columns(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "sentinel.datasources.main_force.requests.get",
        lambda url, params=None, timeout=None: _FakeResponse(
            {"msg": "success", "status": 200, "data": []}
        ),
    )

    df = fetch_trading_daily_report(
        "5347", date(2026, 6, 2), date(2026, 6, 9), _settings("token-x")
    )

    assert df.empty
    assert list(df.columns) == REPORT_COLUMNS


def test_fetch_level_insufficient_surfaces_api_msg(monkeypatch: pytest.MonkeyPatch) -> None:
    level_msg = "Your level is free. Please update your user level..."
    monkeypatch.setattr(
        "sentinel.datasources.main_force.requests.get",
        lambda url, params=None, timeout=None: _FakeResponse(
            {"msg": level_msg, "status": 400}, status_code=400
        ),
    )

    with pytest.raises(FinMindError) as excinfo:
        fetch_trading_daily_report(
            "5347", date(2026, 6, 2), date(2026, 6, 9), _settings("free-token")
        )

    assert level_msg in str(excinfo.value)


def test_fetch_network_error_wrapped_as_finmind_error(monkeypatch: pytest.MonkeyPatch) -> None:
    import requests as _requests

    def _boom(url, params=None, timeout=None):
        raise _requests.ConnectionError("connection refused")

    monkeypatch.setattr("sentinel.datasources.main_force.requests.get", _boom)

    with pytest.raises(FinMindError):
        fetch_trading_daily_report("5347", date(2026, 6, 2), date(2026, 6, 9), _settings("token-x"))


def test_fetch_network_error_redacts_token(monkeypatch: pytest.MonkeyPatch) -> None:
    """requests 例外訊息中的 token 不得出現在 FinMindError 裡。"""
    import requests as _requests

    secret = "SECRET-TOKEN-123"

    def _boom(url, params=None, timeout=None):
        raise _requests.ConnectionError(
            f"Max retries exceeded with url: /?dataset=X&token={secret}"
        )

    monkeypatch.setattr("sentinel.datasources.main_force.requests.get", _boom)

    with pytest.raises(FinMindError) as excinfo:
        fetch_trading_daily_report("5347", date(2026, 6, 2), date(2026, 6, 9), _settings(secret))

    assert secret not in str(excinfo.value)


# ═══════════════════════════════════════════════════════════════════════════
# upsert_main_force_daily（in-memory sqlite round-trip）
# ═══════════════════════════════════════════════════════════════════════════


def _mf_frame(rows: list) -> pd.DataFrame:
    return pd.DataFrame(rows, columns=["trading_date", "main_buy", "main_sell", "main_net"])


def test_upsert_main_force_daily_round_trip() -> None:
    engine = create_db_engine("sqlite://")
    create_schema(engine)
    frame = _mf_frame(
        [
            [date(2026, 6, 9), 150000, -110000, 40000],
            [date(2026, 6, 10), 30000, -10000, 20000],
        ]
    )

    with Session(engine) as session:
        count = upsert_main_force_daily(session, "TPEX", "5347", frame, top_n=15)
        session.commit()

    assert count == 2
    with Session(engine) as session:
        rows = session.query(MainForceDaily).order_by(MainForceDaily.trading_date.asc()).all()
        assert [(r.market, r.symbol) for r in rows] == [("TPEX", "5347")] * 2
        assert rows[0].main_buy == 150000
        assert rows[0].main_sell == -110000
        assert rows[0].main_net == 40000
        assert rows[0].top_n == 15
        assert rows[0].updated_at is not None


def test_upsert_main_force_daily_conflict_updates() -> None:
    engine = create_db_engine("sqlite://")
    create_schema(engine)

    with Session(engine) as session:
        upsert_main_force_daily(
            session, "TPEX", "5347", _mf_frame([[date(2026, 6, 9), 100, -50, 50]]), top_n=15
        )
        session.commit()
    with Session(engine) as session:
        upsert_main_force_daily(
            session, "TPEX", "5347", _mf_frame([[date(2026, 6, 9), 200, -80, 120]]), top_n=10
        )
        session.commit()

    with Session(engine) as session:
        rows = session.query(MainForceDaily).all()
        assert len(rows) == 1
        assert rows[0].main_buy == 200
        assert rows[0].main_sell == -80
        assert rows[0].main_net == 120
        assert rows[0].top_n == 10


def test_upsert_main_force_daily_empty_frame_returns_zero() -> None:
    engine = create_db_engine("sqlite://")
    create_schema(engine)

    with Session(engine) as session:
        count = upsert_main_force_daily(
            session, "TWSE", "2330", pd.DataFrame(columns=["trading_date"]), top_n=15
        )

    assert count == 0
