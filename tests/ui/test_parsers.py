"""測試 CLI 輸出解析器。"""

from __future__ import annotations


def test_parse_run_output_hits() -> None:
    """能從 run stdout 解析出 total_hits。"""
    from ui.services.parsers import parse_run_output

    stdout = '{"event": "scan_complete", "total_hits": 42, "trading_date": "2024-01-15"}'
    result = parse_run_output(stdout, "")
    assert result["hits"] == 42
    assert result["trading_date"] == "2024-01-15"


def test_parse_run_output_no_hits() -> None:
    """無命中數時 hits 應為 None。"""
    from ui.services.parsers import parse_run_output

    result = parse_run_output("OK", "")
    assert result["hits"] is None


def test_parse_sync_output_rows() -> None:
    """能從 sync stdout 解析出 rows 數量。"""
    from ui.services.parsers import parse_sync_output

    stdout = '{"rows": 150, "markets": ["TWSE"]}'
    result = parse_sync_output(stdout, "")
    assert result["rows"] == 150
    assert "TWSE" in result["markets"]


def test_parse_check_stock_triggered() -> None:
    """能識別觸發與未觸發的訊號行。"""
    from ui.services.parsers import parse_check_stock_output

    stdout = "✓ 均線多頭排列 TRIGGERED\n✗ RSI 超賣 NOT TRIGGERED\n"
    result = parse_check_stock_output(stdout, "")
    assert len(result["triggered"]) >= 1
    assert len(result["not_triggered"]) >= 1


def test_parse_generic_output() -> None:
    """通用解析器應回傳行列表。"""
    from ui.services.parsers import parse_generic_output

    stdout = "line1\nline2\nline3\n"
    result = parse_generic_output(stdout, "")
    assert len(result["lines"]) == 3
    assert result["lines"][0] == "line1"
