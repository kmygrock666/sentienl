"""策略條件編輯邏輯層：條件 schema 驗證、套用編輯與 data_editor 列清理。"""

from __future__ import annotations

import copy
from typing import Any

import pandas as pd
from jsonschema import Draft202012Validator

CONDITION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["name", "field", "operator"],
    "properties": {
        "name": {"type": "string"},
        "field": {"type": "string"},
        "operator": {"enum": [">", ">=", "<", "<=", "==", "!="]},
        "target": {"type": "string"},
        "value": {"type": "number"},
        "multiplier": {"type": "number"},
        "consecutive_days": {"type": "integer", "minimum": 1},
    },
    "oneOf": [
        {"required": ["target"], "not": {"required": ["value"]}},
        {"required": ["value"], "not": {"required": ["target"]}},
    ],
    "additionalProperties": False,
}

_VALIDATOR = Draft202012Validator(CONDITION_SCHEMA)


def validate_conditions(conditions: list[dict]) -> list[str]:
    """逐條驗證 conditions，回傳人類可讀錯誤訊息；空 list 表示全部合法。"""
    if not conditions:
        return ["條件不可為空：至少需要 1 個條件"]

    errors: list[str] = []
    for i, cond in enumerate(conditions):
        label = cond.get("name") if isinstance(cond, dict) else None
        prefix = f"條件 #{i + 1}" + (f"（{label}）" if label else "")
        for err in _VALIDATOR.iter_errors(cond):
            if err.validator == "oneOf":
                message = "必須恰好填寫 target（字串）或 value（數值）其中之一"
            else:
                message = err.message
            errors.append(f"{prefix}: {message}")
    return errors


def apply_condition_edits(raw_config: dict, strategy_id: str, conditions: list[dict]) -> dict:
    """回傳替換指定策略 conditions 後的新設定 dict（不修改輸入）。

    找不到 strategy_id 時拋出 ValueError。
    """
    updated = copy.deepcopy(raw_config)
    for key in ("long_strategies", "short_strategies"):
        for strategy in updated.get(key, []):
            if strategy.get("strategy_id") == strategy_id:
                strategy.setdefault("params_json", {})["conditions"] = copy.deepcopy(conditions)
                return updated
    raise ValueError(f"找不到策略：{strategy_id}")


def _is_missing(value: Any) -> bool:
    """純量安全的缺值判斷（None / NaN）。"""
    result = pd.isna(value)
    return bool(result) if isinstance(result, bool) else False


def clean_editor_rows(rows: list[dict]) -> list[dict]:
    """清理 data_editor 輸出列：去除缺值欄位並做型別轉換。

    - 丟棄 None/NaN 欄位
    - value / multiplier 轉 float，consecutive_days 轉 int
    - target 與 value 同時存在且 target 為空字串時丟棄 target
    """
    cleaned: list[dict] = []
    for row in rows:
        new_row = {k: v for k, v in row.items() if not _is_missing(v)}
        if "value" in new_row:
            new_row["value"] = float(new_row["value"])
        if "multiplier" in new_row:
            new_row["multiplier"] = float(new_row["multiplier"])
        if "consecutive_days" in new_row:
            new_row["consecutive_days"] = int(new_row["consecutive_days"])
        if "target" in new_row and "value" in new_row and new_row["target"] == "":
            del new_row["target"]
        cleaned.append(new_row)
    return cleaned
