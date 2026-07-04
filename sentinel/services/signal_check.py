from __future__ import annotations

from typing import List, Tuple


def convert_signals_to_strategies(signals: List[dict]) -> Tuple[List[dict], List[dict]]:
    """把 signals.json 的訊號設定轉成 scan_strategies 可執行的策略格式。

    回傳 (runnable, not_runnable)：需要盤中資料、大盤廣度、缺口偵測或
    非自動規則的訊號無法離線檢驗，原樣歸入 not_runnable。
    """
    runnable: List[dict] = []
    not_runnable: List[dict] = []
    for sig in signals:
        params = sig.get("params", {})
        if (
            sig.get("requires_intraday")
            or sig.get("requires_market_breadth")
            or sig.get("requires_gap_detection")
            or not sig.get("is_active", True)
        ):
            not_runnable.append(sig)
            continue
        runnable.append(
            {
                "strategy_id": sig["signal_id"],
                "name": sig["name"],
                "version": sig.get("version", "1.0.0"),
                "description": sig.get("description", ""),
                "is_active": True,
                "params_json": {
                    "min_history_days": params.get("min_history_days", 25),
                    "direction": sig.get("direction", "long"),
                    "conditions": params.get("conditions", []),
                },
                "backtest": {},
            }
        )
    return runnable, not_runnable
