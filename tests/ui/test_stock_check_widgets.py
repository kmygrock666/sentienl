"""Stock Check widget 純邏輯測試：綜合研判、外資連買、收盤摘要、篩選排序。"""

from __future__ import annotations

import pandas as pd
import pytest

from ui.components.stock_check.signal_cards import FILTERS, match_filter, sort_key
from ui.components.stock_check.summary import (
    VERDICT_MIXED,
    VERDICT_NONE,
    VERDICT_SINGLE,
    VERDICT_STRONG,
    VERDICT_WARNING_ONLY,
    compute_verdict,
    foreign_buy_streak,
    latest_close_summary,
)


@pytest.mark.unit
@pytest.mark.parametrize(
    ("triggered", "warning", "expected"),
    [
        (0, 0, VERDICT_NONE),
        (0, 1, VERDICT_WARNING_ONLY),
        (2, 0, VERDICT_STRONG),
        (3, 0, VERDICT_STRONG),
        (1, 1, VERDICT_MIXED),
        (2, 2, VERDICT_MIXED),
        (1, 0, VERDICT_SINGLE),
    ],
)
def test_compute_verdict(triggered: int, warning: int, expected: tuple) -> None:
    assert compute_verdict(triggered, warning) == expected


@pytest.mark.unit
def test_foreign_buy_streak_counts_until_first_non_positive() -> None:
    df = pd.DataFrame({"外資": [100, 50, -3, 200]})  # 新 → 舊
    assert foreign_buy_streak(df) == 2


@pytest.mark.unit
def test_foreign_buy_streak_handles_na_and_empty() -> None:
    assert foreign_buy_streak(None) == 0
    assert foreign_buy_streak(pd.DataFrame()) == 0
    df = pd.DataFrame({"外資": pd.array([pd.NA, 100], dtype="Int64")})
    assert foreign_buy_streak(df) == 0


@pytest.mark.unit
def test_latest_close_summary_with_delta() -> None:
    df = pd.DataFrame({"close": [100.0, 102.5]})  # 昇冪：舊 → 新
    close, delta = latest_close_summary(df)
    assert close == 102.5
    assert delta is not None
    assert delta.startswith("+2.50")
    assert "+2.50%" in delta


@pytest.mark.unit
def test_latest_close_summary_single_row_has_no_delta() -> None:
    close, delta = latest_close_summary(pd.DataFrame({"close": [55.0]}))
    assert close == 55.0
    assert delta is None
    assert latest_close_summary(None) == (None, None)
    assert latest_close_summary(pd.DataFrame()) == (None, None)


def _sig(status: str, direction: str) -> dict:
    return {"status": status, "direction": direction}


@pytest.mark.unit
def test_match_filter_by_category() -> None:
    long_hit = _sig("triggered", "long")
    warn_hit = _sig("triggered", "warning")
    miss = _sig("not_triggered", "long")
    intraday = _sig("needs_intraday", "intraday")

    assert match_filter(long_hit, "只看觸發")
    assert not match_filter(warn_hit, "只看觸發")
    assert match_filter(warn_hit, "只看警示")
    assert match_filter(miss, "只看未觸發")
    assert match_filter(intraday, "只看需盤中")
    assert all(match_filter(s, "全部") for s in [long_hit, warn_hit, miss, intraday])
    assert "全部" in FILTERS


@pytest.mark.unit
def test_sort_key_priority_order() -> None:
    ordered = [
        _sig("triggered", "long"),
        _sig("triggered", "warning"),
        _sig("not_triggered", "long"),
        _sig("needs_intraday", "intraday"),
    ]
    assert [sort_key(s) for s in ordered] == [0, 1, 2, 3]
