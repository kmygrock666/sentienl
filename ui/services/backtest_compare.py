"""回測結果比較邏輯層：run 探索、報表載入與權益曲線重建。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd

_FALLBACK_INITIAL_CAPITAL = 100000.0


def discover_backtest_runs(backtests_dir: Path) -> list[dict[str, Any]]:
    """列出 backtests_dir 下含 report.csv 的 run 目錄，依 report.csv mtime 由新到舊排序。

    每筆回傳 {"run_id": 目錄名, "path": Path, "metadata": dict | None}；
    目錄不存在時回傳空 list。
    """
    if not backtests_dir.is_dir():
        return []

    runs: list[dict[str, Any]] = []
    for sub in backtests_dir.iterdir():
        report_path = sub / "report.csv"
        if not sub.is_dir() or not report_path.is_file():
            continue
        metadata: dict[str, Any] | None = None
        metadata_path = sub / "metadata.json"
        if metadata_path.is_file():
            try:
                metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                metadata = None
        runs.append({"run_id": sub.name, "path": sub, "metadata": metadata})

    return sorted(runs, key=lambda r: (r["path"] / "report.csv").stat().st_mtime, reverse=True)


def load_run_report(path: Path) -> pd.DataFrame:
    """讀取 run 目錄下的 report.csv，並加上 run_id 欄位（= 目錄名）。"""
    report = pd.read_csv(path / "report.csv")
    return report.assign(run_id=path.name)


def build_equity_curves(trades: pd.DataFrame) -> pd.DataFrame:
    """由 trades 建立長格式權益曲線 [strategy_id, exit_date, balance]。

    各策略依 exit_date 排序；若 balance 欄位缺失或全為 NaN，
    以 (1 + trade_return) 累乘 × 100000 重建；exit_date 為 NaN 的列剔除。
    """
    df = trades.dropna(subset=["exit_date"]).copy()
    df["exit_date"] = pd.to_datetime(df["exit_date"])

    curves: list[pd.DataFrame] = []
    for strategy_id, group in df.groupby("strategy_id", sort=False):
        ordered = group.sort_values("exit_date")
        if "balance" in ordered.columns and ordered["balance"].notna().any():
            balance = ordered["balance"]
        else:
            balance = (1 + ordered["trade_return"]).cumprod() * _FALLBACK_INITIAL_CAPITAL
        curves.append(
            pd.DataFrame(
                {
                    "strategy_id": strategy_id,
                    "exit_date": ordered["exit_date"],
                    "balance": balance,
                }
            )
        )

    if not curves:
        return pd.DataFrame(columns=["strategy_id", "exit_date", "balance"])
    return pd.concat(curves, ignore_index=True)
