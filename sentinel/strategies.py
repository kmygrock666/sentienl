from __future__ import annotations

import datetime as _dt
import json
from pathlib import Path
from typing import Any, Dict, Iterable, Optional

import pandas as pd


DEFAULT_STRATEGY_DEFINITIONS = [
    {
        "strategy_id": "mvp_ma_crossover",
        "name": "MVP MA Crossover",
        "version": "1.1.0",
        "description": "close > ma5 and ma5 > ma20",
        "is_active": True,
        "params_json": {
            "min_history_days": 25,
            "conditions": [
                {"name": "close_gt_ma5", "field": "close", "operator": ">", "target": "ma5"},
                {"name": "ma5_gt_ma20", "field": "ma5", "operator": ">", "target": "ma20"},
            ],
        },
        "backtest": {"holding_period_days": 5, "execution_model_version": "next_open_to_close"},
    },
    {
        "strategy_id": "rsi_pullback",
        "name": "RSI Pullback",
        "version": "1.0.0",
        "description": "close > ma20 and rsi14 < 35",
        "is_active": True,
        "params_json": {
            "min_history_days": 25,
            "conditions": [
                {"name": "close_gt_ma20", "field": "close", "operator": ">", "target": "ma20"},
                {"name": "rsi14_lt_35", "field": "rsi14", "operator": "<", "value": 35},
            ],
        },
        "backtest": {"holding_period_days": 5, "execution_model_version": "next_open_to_close"},
    },
    {
        "strategy_id": "volume_breakout",
        "name": "Volume Breakout",
        "version": "1.0.0",
        "description": "close > bb_upper_20 and volume > volume_ma5 * 2",
        "is_active": True,
        "params_json": {
            "min_history_days": 25,
            "conditions": [
                {"name": "close_gt_bb_upper_20", "field": "close", "operator": ">", "target": "bb_upper_20"},
                {"name": "volume_gt_2x_volume_ma5", "field": "volume", "operator": ">", "target": "volume_ma5", "multiplier": 2.0},
            ],
        },
        "backtest": {"holding_period_days": 3, "execution_model_version": "next_open_to_close"},
    },
]


def load_strategy_definitions(path: Optional[Path] = None) -> list[dict]:
    if path is None:
        return [dict(strategy) for strategy in DEFAULT_STRATEGY_DEFINITIONS]
    if not path.exists():
        return [dict(strategy) for strategy in DEFAULT_STRATEGY_DEFINITIONS]

    suffix = path.suffix.lower()
    payload = path.read_text(encoding="utf-8")
    if suffix == ".json":
        loaded = json.loads(payload)
        return _normalize_strategy_definitions(loaded)
    if suffix in {".yml", ".yaml"}:
        try:
            import yaml
        except ImportError as exc:  # pragma: no cover - optional dependency path
            raise RuntimeError("PyYAML is required to load YAML strategy files") from exc
        loaded = yaml.safe_load(payload)
        return _normalize_strategy_definitions(loaded)
    raise ValueError("Unsupported strategy config format: {0}".format(path.suffix))


def scan_strategies(
    prices_with_indicators: pd.DataFrame,
    trading_date,
    strategies: Iterable[dict],
) -> pd.DataFrame:
    if prices_with_indicators.empty:
        return pd.DataFrame(columns=_scan_result_columns())

    # ── 前處理 ────────────────────────────────────────────────────────────
    # 快速路徑：compute_indicator_frame 輸出的 frame 已是排序好的 date 物件，
    # 可省略 copy / convert / sort，節省約 0.4s（2000 檔 × 400 天規模）。
    td_sample = prices_with_indicators["trading_date"].iloc[0]
    if isinstance(td_sample, _dt.date) and not isinstance(td_sample, _dt.datetime):
        frame = prices_with_indicators  # 無需複製，只讀
    else:
        frame = prices_with_indicators.copy()
        frame["trading_date"] = pd.to_datetime(frame["trading_date"]).dt.date
        frame = frame.sort_values(["market", "symbol", "trading_date"]).reset_index(drop=True)

    today = frame[frame["trading_date"] == trading_date]
    if today.empty:
        return pd.DataFrame(columns=_scan_result_columns())

    # ── 全域過濾（向量化，移出 per-strategy loop）────────────────────────
    if "is_pure_stock" in today.columns:
        today = today[today["is_pure_stock"] == 1.0]
    if "is_stuck_data" in today.columns:
        today = today[today["is_stuck_data"] == 0.0]
    if today.empty:
        return pd.DataFrame(columns=_scan_result_columns())

    # frame 在 trading_date 以前（含）的子集，供 min_history 查詢使用
    _frame_upto: Optional[pd.DataFrame] = None

    results = []
    for strategy in strategies:
        if not strategy.get("is_active", True):
            continue

        params = strategy["params_json"]
        conditions = params.get("conditions", [])
        min_history_days = int(params.get("min_history_days", 1))

        # 區分單日（可直接向量化）與多日連續條件
        single_conds = [c for c in conditions if int(c.get("consecutive_days", 1)) == 1]
        multi_conds = [c for c in conditions if int(c.get("consecutive_days", 1)) > 1]

        candidates = today

        # ── 向量化：單日條件（主路徑）────────────────────────────────────
        for cond in single_conds:
            mask = _eval_condition_vectorized(candidates, cond)
            candidates = candidates[mask]
            if candidates.empty:
                break

        if candidates.empty:
            continue

        # ── 向量化：多日連續條件（rolling min 保留完整語意）──────────────
        for cond in multi_conds:
            cons_days = int(cond["consecutive_days"])
            bool_full = _eval_condition_vectorized(frame, cond).astype(float)
            rolling_min = (
                bool_full
                .groupby([frame["market"], frame["symbol"]])
                .transform(lambda x, w=cons_days: x.rolling(window=w, min_periods=w).min())
            )
            today_rolling = rolling_min.loc[frame["trading_date"] == trading_date]
            mask = today_rolling.reindex(candidates.index).fillna(0.0) >= 1.0
            candidates = candidates[mask]
            if candidates.empty:
                break

        if candidates.empty:
            continue

        # ── min_history_days 過濾 ─────────────────────────────────────────
        # 對通過篩選的極少數標的（通常 < 50 筆）做輕量查詢，
        # 避免對整個 frame 做完整 groupby。
        # 注：條件中使用 ma200 等高視窗指標時，NaN 已自然過濾不足歷史的標的，
        # 此處為防禦性補充，以保全正確性。
        if min_history_days > 1:
            if _frame_upto is None:
                _frame_upto = frame[frame["trading_date"] <= trading_date]
            sym_df = candidates[["market", "symbol"]].drop_duplicates()
            sym_counts = (
                _frame_upto.merge(sym_df, on=["market", "symbol"])
                .groupby(["market", "symbol"])
                .size()
                .reset_index(name="_cnt")
            )
            candidates = (
                candidates
                .merge(sym_counts, on=["market", "symbol"], how="left")
                .pipe(lambda d: d[d["_cnt"].fillna(0) >= min_history_days])
                .drop(columns=["_cnt"])
            )
            if candidates.empty:
                continue

        # ── 建立輸出：只遍歷通過篩選的極少數標的 ────────────────────────
        for _, row in candidates.iterrows():
            cond_results = [_build_condition_result_from_row(row, cond) for cond in conditions]
            score = float(sum(1 for r in cond_results if r["passed"])) / max(len(cond_results), 1)
            results.append(
                {
                    "symbol": row["symbol"],
                    "name": row["name"],
                    "market": row["market"],
                    "trading_date": trading_date,
                    "close": _to_float(row.get("close")),
                    "strategy_id": strategy["strategy_id"],
                    "strategy_name": strategy["name"],
                    "direction": params.get("direction", "long"),
                    "score": score,
                    "signal": strategy["strategy_id"],
                    "signals_json": {"conditions": cond_results},
                }
            )

    if not results:
        return pd.DataFrame(columns=_scan_result_columns())

    return pd.DataFrame(results).sort_values(["strategy_id", "market", "symbol"]).reset_index(drop=True)


# ── 向量化條件評估 ────────────────────────────────────────────────────────────

def _eval_condition_vectorized(df: pd.DataFrame, condition: Dict[str, Any]) -> pd.Series:
    """對 DataFrame 向量化評估單一條件，回傳 bool Series。NaN 比較視為 False。"""
    field = condition["field"]
    false_series = pd.Series(False, index=df.index)

    if field not in df.columns:
        return false_series

    left = pd.to_numeric(df[field], errors="coerce")

    if "target" in condition:
        target = condition["target"]
        if target not in df.columns:
            return false_series
        ref: Any = pd.to_numeric(df[target], errors="coerce")
    else:
        val = condition.get("value")
        try:
            ref = float(val) if val is not None else float("nan")
        except (TypeError, ValueError):
            ref = val

    multiplier = float(condition.get("multiplier", 1.0))
    if multiplier != 1.0:
        ref = ref * multiplier

    op = condition["operator"]
    if op == ">":
        result = left > ref
    elif op == ">=":
        result = left >= ref
    elif op == "<":
        result = left < ref
    elif op == "<=":
        result = left <= ref
    elif op == "==":
        result = left == ref
    elif op == "!=":
        result = left != ref
    else:
        return false_series

    return result.fillna(False)


def _build_condition_result_from_row(row: pd.Series, condition: Dict[str, Any]) -> Dict[str, Any]:
    """從今日單列資料建立 condition result（用於 signals_json）。"""
    field = condition["field"]
    left_value = row.get(field)

    if "target" in condition:
        ref_raw = row.get(condition["target"])
        multiplier = float(condition.get("multiplier", 1.0))
        reference_value = (
            float(ref_raw) * multiplier
            if isinstance(ref_raw, (int, float)) and multiplier != 1.0
            else ref_raw
        )
    else:
        reference_value = condition.get("value")

    passed = _compare_values(
        left_value=left_value,
        operator=condition["operator"],
        right_value=reference_value,
    )
    return _build_condition_result(
        condition=condition,
        passed=passed,
        value=left_value,
        reference=reference_value,
    )


# ── 原有輔助函式（保留供測試及 backtest 呼叫）────────────────────────────────

def _evaluate_condition(
    symbol_history: pd.DataFrame, row_index: int, condition: Dict[str, Any]
) -> Dict[str, Any]:
    consecutive_days = max(int(condition.get("consecutive_days", 1)), 1)
    start_index = row_index - consecutive_days + 1
    if start_index < 0:
        return _build_condition_result(condition=condition, passed=False, value=None, reference=None)

    evaluations = []
    for current_index in range(start_index, row_index + 1):
        current_row = symbol_history.iloc[current_index]
        left_value = _extract_value(current_row=current_row, key=condition["field"])
        reference_value = _resolve_reference(current_row=current_row, condition=condition)
        passed = _compare_values(left_value=left_value, operator=condition["operator"], right_value=reference_value)
        evaluations.append((passed, left_value, reference_value))

    final_passed, final_value, final_reference = evaluations[-1]
    all_passed = all(item[0] for item in evaluations)
    return _build_condition_result(
        condition=condition,
        passed=all_passed,
        value=final_value,
        reference=final_reference,
    )


def _normalize_strategy_definitions(loaded: Any) -> list[dict]:
    normalized = []

    if isinstance(loaded, dict):
        if "strategies" in loaded:
            strategies_list = [("long", loaded["strategies"])]
        else:
            strategies_list = [
                ("long", loaded.get("long_strategies", [])),
                ("short", loaded.get("short_strategies", [])),
            ]
    else:
        strategies_list = [("long", loaded)]

    for direction, strategies in strategies_list:
        if not strategies:
            continue
        for strategy in strategies:
            p_json = dict(strategy.get("params_json") or strategy.get("params") or {})
            p_json["direction"] = direction
            normalized.append(
                {
                    "strategy_id": str(strategy["strategy_id"]),
                    "name": str(strategy.get("name") or strategy["strategy_id"]),
                    "version": str(strategy.get("version") or "1.0.0"),
                    "description": strategy.get("description"),
                    "is_active": bool(strategy.get("is_active", True)),
                    "params_json": p_json,
                    "backtest": dict(strategy.get("backtest") or {}),
                }
            )
    return normalized


def _resolve_reference(current_row: pd.Series, condition: Dict[str, Any]) -> Any:
    if "target" in condition:
        reference_value = _extract_value(current_row=current_row, key=condition["target"])
    else:
        reference_value = condition.get("value")
    multiplier = float(condition.get("multiplier", 1.0))
    if isinstance(reference_value, (int, float)) and multiplier != 1.0:
        return float(reference_value) * multiplier
    return reference_value


def _extract_value(current_row: pd.Series, key: str) -> Any:
    return current_row.get(key)


def _compare_values(left_value: Any, operator: str, right_value: Any) -> bool:
    if pd.isna(left_value) or pd.isna(right_value):
        return False
    if operator == ">":
        return bool(left_value > right_value)
    if operator == ">=":
        return bool(left_value >= right_value)
    if operator == "<":
        return bool(left_value < right_value)
    if operator == "<=":
        return bool(left_value <= right_value)
    if operator == "==":
        return bool(left_value == right_value)
    if operator == "!=":
        return bool(left_value != right_value)
    raise ValueError("Unsupported operator: {0}".format(operator))


def _build_condition_result(
    condition: Dict[str, Any], passed: bool, value: Any, reference: Any
) -> Dict[str, Any]:
    target = condition.get("target", condition.get("value"))
    return {
        "name": condition.get("name") or "{0}_{1}_{2}".format(condition["field"], condition["operator"], target),
        "field": condition["field"],
        "operator": condition["operator"],
        "passed": bool(passed),
        "value": _to_float(value),
        "reference": _to_float(reference) if isinstance(reference, (int, float)) or not pd.isna(reference) else None,
        "target": target,
    }


def _to_float(value: Any) -> Any:
    if value is None or pd.isna(value):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return value


def _scan_result_columns() -> list[str]:
    return [
        "symbol",
        "name",
        "market",
        "trading_date",
        "close",
        "strategy_id",
        "strategy_name",
        "direction",
        "score",
        "signal",
        "signals_json",
    ]
