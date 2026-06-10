"""測試策略條件編輯邏輯層（strategy_editor）。"""

from __future__ import annotations

import copy

import numpy as np
import pytest

from ui.services.strategy_editor import (
    apply_condition_edits,
    clean_editor_rows,
    validate_conditions,
)


def _valid_condition(**overrides: object) -> dict:
    base: dict = {"name": "close_gt_ma5", "field": "close", "operator": ">", "target": "ma5"}
    base.update(overrides)
    return base


def _raw_config() -> dict:
    return {
        "long_strategies": [
            {
                "strategy_id": "mvp_ma_crossover",
                "name": "黃金交叉",
                "is_active": True,
                "params_json": {
                    "min_history_days": 200,
                    "conditions": [_valid_condition()],
                },
            }
        ],
        "short_strategies": [
            {
                "strategy_id": "bearish_breakdown",
                "name": "跌破",
                "is_active": False,
                "params_json": {
                    "min_history_days": 60,
                    "conditions": [
                        {
                            "name": "close_lt_ma20",
                            "field": "close",
                            "operator": "<",
                            "target": "ma20",
                        }
                    ],
                },
            }
        ],
    }


# ── validate_conditions ─────────────────────────────────────────────────────


@pytest.mark.unit
def test_validate_conditions_valid_passes():
    conditions = [
        _valid_condition(),
        {"name": "vol_ratio", "field": "volume", "operator": ">=", "value": 1.5, "multiplier": 2.0},
        {
            "name": "streak",
            "field": "close",
            "operator": ">",
            "target": "ma5",
            "consecutive_days": 3,
        },
    ]
    assert validate_conditions(conditions) == []


@pytest.mark.unit
def test_validate_conditions_invalid_operator_caught():
    errors = validate_conditions([_valid_condition(operator="><")])
    assert len(errors) == 1
    assert "close_gt_ma5" in errors[0]


@pytest.mark.unit
def test_validate_conditions_both_target_and_value_caught():
    errors = validate_conditions([_valid_condition(value=1.0)])
    assert errors


@pytest.mark.unit
def test_validate_conditions_neither_target_nor_value_caught():
    cond = _valid_condition()
    del cond["target"]
    assert validate_conditions([cond])


@pytest.mark.unit
def test_validate_conditions_missing_field_caught():
    cond = _valid_condition()
    del cond["field"]
    errors = validate_conditions([cond])
    assert errors
    assert "#1" in errors[0]


@pytest.mark.unit
def test_validate_conditions_empty_list_caught():
    assert validate_conditions([])


@pytest.mark.unit
def test_validate_conditions_consecutive_days_minimum():
    assert validate_conditions([_valid_condition(consecutive_days=0)])
    assert validate_conditions([_valid_condition(consecutive_days=2)]) == []


@pytest.mark.unit
def test_validate_conditions_additional_properties_rejected():
    assert validate_conditions([_valid_condition(bogus_key=1)])


# ── apply_condition_edits ───────────────────────────────────────────────────


@pytest.mark.unit
def test_apply_condition_edits_replaces_conditions():
    raw = _raw_config()
    new_conditions = [_valid_condition(name="new_cond", target="ma60")]
    updated = apply_condition_edits(raw, "mvp_ma_crossover", new_conditions)
    assert updated["long_strategies"][0]["params_json"]["conditions"] == new_conditions


@pytest.mark.unit
def test_apply_condition_edits_finds_short_strategies():
    raw = _raw_config()
    new_conditions = [_valid_condition(name="short_cond", operator="<")]
    updated = apply_condition_edits(raw, "bearish_breakdown", new_conditions)
    assert updated["short_strategies"][0]["params_json"]["conditions"] == new_conditions


@pytest.mark.unit
def test_apply_condition_edits_does_not_mutate_input():
    raw = _raw_config()
    snapshot = copy.deepcopy(raw)
    apply_condition_edits(raw, "mvp_ma_crossover", [_valid_condition(name="changed")])
    assert raw == snapshot


@pytest.mark.unit
def test_apply_condition_edits_unknown_id_raises():
    with pytest.raises(ValueError, match="no_such_id"):
        apply_condition_edits(_raw_config(), "no_such_id", [_valid_condition()])


# ── clean_editor_rows ───────────────────────────────────────────────────────


@pytest.mark.unit
def test_clean_editor_rows_drops_nan_and_none():
    rows = [
        {
            "name": "c1",
            "field": "close",
            "operator": ">",
            "target": "ma5",
            "value": np.nan,
            "multiplier": None,
            "consecutive_days": np.nan,
        }
    ]
    assert clean_editor_rows(rows) == [
        {"name": "c1", "field": "close", "operator": ">", "target": "ma5"}
    ]


@pytest.mark.unit
def test_clean_editor_rows_coerces_types():
    rows = [
        {
            "name": "c1",
            "field": "volume",
            "operator": ">=",
            "value": np.float64(1.5),
            "multiplier": "2",
            "consecutive_days": 3.0,
        }
    ]
    cleaned = clean_editor_rows(rows)
    assert cleaned == [
        {
            "name": "c1",
            "field": "volume",
            "operator": ">=",
            "value": 1.5,
            "multiplier": 2.0,
            "consecutive_days": 3,
        }
    ]
    assert isinstance(cleaned[0]["value"], float)
    assert isinstance(cleaned[0]["multiplier"], float)
    assert isinstance(cleaned[0]["consecutive_days"], int)


@pytest.mark.unit
def test_clean_editor_rows_drops_empty_target_when_value_present():
    rows = [{"name": "c1", "field": "close", "operator": ">", "target": "", "value": 1.0}]
    assert clean_editor_rows(rows) == [
        {"name": "c1", "field": "close", "operator": ">", "value": 1.0}
    ]


@pytest.mark.unit
def test_clean_editor_rows_does_not_mutate_input():
    rows = [{"name": "c1", "field": "close", "operator": ">", "target": "ma5", "value": np.nan}]
    snapshot = copy.deepcopy(rows[0])
    clean_editor_rows(rows)
    assert rows[0].keys() == snapshot.keys()
