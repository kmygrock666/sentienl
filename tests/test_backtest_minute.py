"""run_minute_backtest 編排邏輯測試。

重點：標準模式與 tomorrow_star 模式都應共用「逐訊號模擬 → 候選 → 資金邏輯」流程，
過去這段被誤關在 else 分支、且引用了未定義變數（strategy_signals / strategy /
take_profit_pct / limit_up_pct / trades），任一模式實際執行都會 NameError。
"""

from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

import sentinel.backtest_minute as bm


def _prices_one_row() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "market": "TWSE",
                "symbol": "2330",
                "trading_date": date(2026, 3, 5),
                "open": 100.0,
                "high": 101.0,
                "low": 99.0,
                "close": 100.5,
                "volume": 1000,
            }
        ]
    )


def _strategy_with_minute_cfg() -> dict:
    return {
        "strategy_id": "s1",
        "name": "策略一",
        "backtest": {"minute_bar_execution": {"take_profit_pct": 0.05, "limit_up_pct": 0.10}},
    }


@pytest.mark.unit
def test_standard_mode_resolves_strategy_and_returns_without_nameerror(monkeypatch):
    """標準模式：每筆訊號應解析出對應策略與停利/漲停參數，無候選時乾淨回傳空表。"""
    signal = pd.DataFrame(
        [
            {
                "strategy_id": "s1",
                "market": "TWSE",
                "symbol": "2330",
                "trading_date": date(2026, 3, 5),
            }
        ]
    )
    monkeypatch.setattr(bm, "scan_strategies", lambda *a, **k: signal)

    captured = {}

    def fake_sim(**kwargs):
        captured["strategy_id"] = kwargs["strategy"]["strategy_id"]
        captured["take_profit_pct"] = kwargs["take_profit_pct"]
        captured["limit_up_pct"] = kwargs["limit_up_pct"]
        return None  # 不產生候選，避免依賴分鐘 K 線/DB

    monkeypatch.setattr(bm, "_simulate_single_trade", fake_sim)

    reports, trades = bm.run_minute_backtest(
        _prices_one_row(),
        [_strategy_with_minute_cfg()],
        start_date=date(2026, 3, 5),
        end_date=date(2026, 3, 5),
        daily_session=None,
        intraday_session=None,
    )

    assert reports.empty and trades.empty
    assert captured["strategy_id"] == "s1"
    assert captured["take_profit_pct"] == 0.05  # 取自策略 backtest 設定
    assert captured["limit_up_pct"] == 0.10


@pytest.mark.unit
def test_standard_mode_take_profit_falls_back_to_default(monkeypatch):
    """策略未設定 minute_bar_execution 時，停利應退回 DEFAULT_TAKE_PROFIT_PCT。"""
    signal = pd.DataFrame(
        [
            {
                "strategy_id": "s1",
                "market": "TWSE",
                "symbol": "2330",
                "trading_date": date(2026, 3, 5),
            }
        ]
    )
    monkeypatch.setattr(bm, "scan_strategies", lambda *a, **k: signal)

    captured = {}

    def fake_sim(**kwargs):
        captured["take_profit_pct"] = kwargs["take_profit_pct"]
        captured["limit_up_pct"] = kwargs["limit_up_pct"]
        return None

    monkeypatch.setattr(bm, "_simulate_single_trade", fake_sim)

    reports, trades = bm.run_minute_backtest(
        _prices_one_row(),
        [{"strategy_id": "s1", "name": "策略一"}],  # 無 backtest 設定
        start_date=date(2026, 3, 5),
        end_date=date(2026, 3, 5),
        daily_session=None,
        intraday_session=None,
    )

    assert reports.empty and trades.empty
    assert captured["take_profit_pct"] == bm.DEFAULT_TAKE_PROFIT_PCT
    assert captured["limit_up_pct"] == bm.LIMIT_UP_PCT


@pytest.mark.unit
def test_tomorrow_star_mode_returns_without_nameerror(monkeypatch):
    """tomorrow_star 模式：應共用同一處理流程，不再掉到未定義的 trades 變數。"""
    signal = pd.DataFrame(
        [
            {
                "strategy_id": "tomorrow_star",
                "market": "TWSE",
                "symbol": "2330",
                "trading_date": date(2026, 3, 5),
            }
        ]
    )
    monkeypatch.setattr(
        "sentinel.intraday.historical_signals.generate_tomorrow_star_signals",
        lambda *a, **k: signal,
    )
    monkeypatch.setattr(bm, "_simulate_single_trade", lambda **k: None)

    reports, trades = bm.run_minute_backtest(
        _prices_one_row(),
        [{"strategy_id": "tomorrow_star", "name": "明日之星"}],
        start_date=date(2026, 3, 5),
        end_date=date(2026, 3, 5),
        daily_session=None,
        intraday_session=None,
        strategy_mode="tomorrow_star",
    )

    assert reports.empty and trades.empty
