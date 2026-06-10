"""測試回測結果比較邏輯層（backtest_compare）。"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pandas as pd
import pytest

REPORT_COLUMNS = [
    "strategy_id",
    "strategy_name",
    "trades",
    "win_rate",
    "avg_trade_return",
    "total_return",
    "cagr",
    "mdd",
    "turnover",
    "benchmark_symbol",
    "benchmark_total_return",
    "exit_reasons",
    "initial_capital",
    "final_balance",
]


def _write_report(run_dir: Path) -> None:
    df = pd.DataFrame(
        [
            {
                "strategy_id": "bullish_3d_breakout",
                "strategy_name": "3D線收盤突破",
                "trades": 1,
                "win_rate": 0.0,
                "avg_trade_return": -0.0151,
                "total_return": -0.0151,
                "cagr": -0.0068,
                "mdd": 0.0,
                "turnover": 0.449,
                "benchmark_symbol": None,
                "benchmark_total_return": None,
                "exit_reasons": None,
                "initial_capital": 100000.0,
                "final_balance": 98489.4,
            }
        ],
        columns=REPORT_COLUMNS,
    )
    df.to_csv(run_dir / "report.csv", index=False)


def _write_trades(run_dir: Path, with_balance: bool) -> None:
    rows = [
        {
            "strategy_id": "s1",
            "strategy_name": "策略一",
            "symbol": "1232",
            "name": "大統益",
            "market": "TWSE",
            "signal_date": "2025-05-29",
            "entry_date": "2025-06-02",
            "exit_date": "2025-06-02",
            "entry_price": 165.5,
            "exit_price": 163.0,
            "holding_period_days": 5,
            "trade_return": -0.01,
            "execution_model_version": "next_open_to_close",
            "balance": 99000.0 if with_balance else None,
        },
        {
            "strategy_id": "s1",
            "strategy_name": "策略一",
            "symbol": "2330",
            "name": "台積電",
            "market": "TWSE",
            "signal_date": "2025-06-03",
            "entry_date": "2025-06-04",
            "exit_date": "2025-06-10",
            "entry_price": 900.0,
            "exit_price": 990.0,
            "holding_period_days": 6,
            "trade_return": 0.10,
            "execution_model_version": "next_open_to_close",
            "balance": 108900.0 if with_balance else None,
        },
    ]
    pd.DataFrame(rows).to_csv(run_dir / "trades.csv", index=False)


@pytest.fixture()
def backtests_dir(tmp_path: Path) -> Path:
    """建立兩個假的回測 run 目錄（mtime 不同以驗證排序）。"""
    base = tmp_path / "backtests"
    old_run = base / "2024-01-01_2026-03-24"
    new_run = base / "minute_2024-03-01_2024-03-20"
    for run_dir in (old_run, new_run):
        run_dir.mkdir(parents=True)
        _write_report(run_dir)
    _write_trades(old_run, with_balance=True)
    _write_trades(new_run, with_balance=False)
    (old_run / "metadata.json").write_text(
        json.dumps({"start_date": "2024-01-01", "end_date": "2026-03-24"}),
        encoding="utf-8",
    )
    # 沒有 report.csv 的目錄不應被列入
    (base / "not_a_run").mkdir()
    # 調整 mtime：old_run 較舊、new_run 較新
    os.utime(old_run / "report.csv", (1_000_000, 1_000_000))
    os.utime(new_run / "report.csv", (2_000_000, 2_000_000))
    return base


# ── discover_backtest_runs ──────────────────────────────────────────────────


def test_discover_runs_sorted_by_mtime_desc(backtests_dir: Path) -> None:
    """應依 report.csv mtime 由新到舊排序，且跳過無 report.csv 的目錄。"""
    from ui.services.backtest_compare import discover_backtest_runs

    runs = discover_backtest_runs(backtests_dir)
    assert [r["run_id"] for r in runs] == [
        "minute_2024-03-01_2024-03-20",
        "2024-01-01_2026-03-24",
    ]
    assert all(isinstance(r["path"], Path) for r in runs)


def test_discover_runs_loads_metadata(backtests_dir: Path) -> None:
    """有 metadata.json 時應解析為 dict，否則為 None。"""
    from ui.services.backtest_compare import discover_backtest_runs

    runs = {r["run_id"]: r for r in discover_backtest_runs(backtests_dir)}
    assert runs["2024-01-01_2026-03-24"]["metadata"] == {
        "start_date": "2024-01-01",
        "end_date": "2026-03-24",
    }
    assert runs["minute_2024-03-01_2024-03-20"]["metadata"] is None


def test_discover_runs_missing_dir_returns_empty(tmp_path: Path) -> None:
    """目錄不存在時應回傳空 list。"""
    from ui.services.backtest_compare import discover_backtest_runs

    assert discover_backtest_runs(tmp_path / "nope") == []


# ── load_run_report ─────────────────────────────────────────────────────────


def test_load_run_report_adds_run_id(backtests_dir: Path) -> None:
    """讀取 report.csv 並加上 run_id 欄位（= 目錄名）。"""
    from ui.services.backtest_compare import load_run_report

    df = load_run_report(backtests_dir / "2024-01-01_2026-03-24")
    assert "run_id" in df.columns
    assert df["run_id"].unique().tolist() == ["2024-01-01_2026-03-24"]
    assert df.loc[0, "strategy_id"] == "bullish_3d_breakout"
    assert len(df) == 1


# ── build_equity_curves ─────────────────────────────────────────────────────


def test_build_equity_curves_uses_balance_column(backtests_dir: Path) -> None:
    """有 balance 欄位時直接使用，並依 exit_date 排序。"""
    from ui.services.backtest_compare import build_equity_curves

    trades = pd.read_csv(backtests_dir / "2024-01-01_2026-03-24" / "trades.csv")
    curves = build_equity_curves(trades)
    assert list(curves.columns) == ["strategy_id", "exit_date", "balance"]
    s1 = curves[curves["strategy_id"] == "s1"]
    assert s1["exit_date"].is_monotonic_increasing
    assert s1["balance"].tolist() == [99000.0, 108900.0]


def test_build_equity_curves_fallback_cumprod(backtests_dir: Path) -> None:
    """balance 全為 NaN 時，以 (1+trade_return) 累乘 × 100000 重建。"""
    from ui.services.backtest_compare import build_equity_curves

    trades = pd.read_csv(backtests_dir / "minute_2024-03-01_2024-03-20" / "trades.csv")
    curves = build_equity_curves(trades)
    balances = curves[curves["strategy_id"] == "s1"]["balance"].tolist()
    assert balances == pytest.approx([99000.0, 108900.0])


def test_build_equity_curves_missing_balance_column() -> None:
    """缺少 balance 欄位時也應走 fallback 重建。"""
    from ui.services.backtest_compare import build_equity_curves

    trades = pd.DataFrame(
        {
            "strategy_id": ["s2", "s2"],
            "exit_date": ["2025-01-10", "2025-01-05"],
            "trade_return": [0.05, 0.10],
        }
    )
    curves = build_equity_curves(trades)
    # 依 exit_date 排序後：先 0.10 再 0.05
    assert curves["balance"].tolist() == pytest.approx([110000.0, 115500.0])


def test_build_equity_curves_drops_nan_exit_date() -> None:
    """exit_date 為 NaN 的列應被剔除。"""
    from ui.services.backtest_compare import build_equity_curves

    trades = pd.DataFrame(
        {
            "strategy_id": ["s1", "s1"],
            "exit_date": ["2025-01-05", None],
            "trade_return": [0.05, 0.10],
            "balance": [105000.0, 115500.0],
        }
    )
    curves = build_equity_curves(trades)
    assert len(curves) == 1
    assert curves.iloc[0]["balance"] == 105000.0
