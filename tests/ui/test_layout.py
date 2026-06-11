"""layout.py HTML helper 的契約測試（escape、class 選擇、缺值處理）。"""

from __future__ import annotations

import pytest

from ui.components.layout import pnl_chip_html, status_badge_html


@pytest.mark.unit
def test_status_badge_known_status_uses_matching_class() -> None:
    out = status_badge_html("running")
    assert 'class="tk-badge running"' in out
    assert "RUNNING" in out


@pytest.mark.unit
def test_status_badge_unknown_status_falls_back_and_escapes() -> None:
    out = status_badge_html("<script>alert(1)</script>")
    assert 'class="tk-badge unknown"' in out
    assert "<script>" not in out  # 已被 escape
    assert "&lt;SCRIPT&gt;" in out


@pytest.mark.unit
def test_pnl_chip_sign_and_class() -> None:
    assert 'class="tk-chip up"' in pnl_chip_html(12.3, "%")
    assert "+12.30%" in pnl_chip_html(12.3, "%")
    assert 'class="tk-chip down"' in pnl_chip_html(-0.5)
    assert 'class="tk-chip flat"' in pnl_chip_html(0.0)


@pytest.mark.unit
def test_pnl_chip_none_renders_dash_and_suffix_escaped() -> None:
    assert "—" in pnl_chip_html(None)
    assert "<b>" not in pnl_chip_html(1.0, "<b>")
